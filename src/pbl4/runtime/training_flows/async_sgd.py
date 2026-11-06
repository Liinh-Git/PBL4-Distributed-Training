"""Async Coordinator: serialize decisions, not network or checkpoint I/O."""

import threading
import time
from dataclasses import replace

from pbl4.common.hashing import canonical_json_bytes
from pbl4.runtime.batch_scheduler import RecoveryCursor
from pbl4.runtime.contribution import ContributionRejected
from pbl4.runtime.coordinator import (
    Coordinator,
    _accumulate_epoch_contributions,
    _compute_epoch_metrics_payload,
)
from pbl4.runtime.heartbeat import HeartbeatMonitor
from pbl4.runtime.worker_registry import SessionState


class AsyncCoordinator(Coordinator):
    def __init__(self, *args, pool, settings, **kwargs):
        super().__init__(*args, **kwargs)
        self.pool = pool
        self.settings = settings
        self._async_policy = self._policy
        self._offers = {}
        self._idle = set()
        self._results = {}
        self._checkpoint_io = threading.Lock()
        self._zero_since = None
        self._last_frontier = pool.frontier
        self._last_staleness = None
        self._last_loss = None
        self._seen_sessions = {m.worker_id: m.session_id for m in self._context.membership}
        self._disconnected_sessions = {}
        self._async_epoch_metrics = {}

    def _processed_epoch_units(self, epoch):
        size = len(self.pool.units)
        start, end = epoch * size, (epoch + 1) * size
        issued = max(0, min(size, self.pool.issued - start))
        return issued - sum(start <= index < end for index in self.pool.remaining)

    def _metrics_for_epoch(self, epoch):
        if epoch not in self._async_epoch_metrics:
            size = len(self.pool.units)
            start = epoch * size
            # Checkpoints restore work/model, not historical measurement sums. Count
            # restored processed samples but keep their loss/accuracy unavailable.
            prior_samples = sum(
                self.pool.unit(index).sample_count
                for index in range(start, min(start + size, self.pool.issued))
                if index not in self.pool.remaining
            )
            self._async_epoch_metrics[epoch] = {
                "sample_count": prior_samples,
                "weighted_loss_sum": 0.0,
                "correct_count": 0,
                "valid": prior_samples == 0,
            }
        return self._async_epoch_metrics[epoch]

    def _epoch_progress(self):
        epoch = self.pool.frontier
        if epoch >= self.pool.epochs:
            return None
        return {
            **_compute_epoch_metrics_payload(self._metrics_for_epoch(epoch), epoch),
            "processed_units": self._processed_epoch_units(epoch),
            "target_units": len(self.pool.units),
        }

    @property
    def accepts_workers(self):
        with self._lock:
            return self._state not in {"FAILED", "ABORTED", "COMPLETED"} and not (
                self._state == "RUNNING" and self.pool.finished
            )

    def advance_initialization(self):
        with self._lock:
            next_state = {
                "CREATED": "WAITING_WORKERS",
                "WAITING_WORKERS": "PROVISIONING",
                "PROVISIONING": "INITIALIZING",
                "INITIALIZING": "RUNNING",
            }[self._state]
            if next_state == "RUNNING":
                sessions = self._registry.snapshot()
                if len(sessions) != self._context.expected_workers or any(
                    s.state != SessionState.READY for s in sessions
                ):
                    return self._state
            self._transition(next_state)
            return next_state

    def offer(self, session, now):
        with self._lock:
            key = (session.worker_id, session.session_id)
            if (
                self._state != "RUNNING"
                or not self._active(*key)
                or session.worker_id in self.pool.assignments
                or key in self._offers
            ):
                return None
            if self._seen_sessions.get(session.worker_id) != session.session_id:
                self._seen_sessions[session.worker_id] = session.session_id
                self._event(
                    "worker.reconnected",
                    {"worker_id": session.worker_id, "session_id": str(session.session_id)},
                )
            snapshot = self._model.snapshot()
            assignment = self.pool.assign(
                session.worker_id, session.session_id, snapshot.model_version, now
            )
            if assignment is None and key in self._idle:
                return None
            # Unique correlation for idle offers as well; never a fake global Step.
            operation = assignment.operation_id if assignment else self.pool.new_operation_id()
            if assignment is None:
                self._idle.add(key)
            self._offers[key] = (operation, snapshot.model_version, assignment is not None, now)
            return snapshot, operation, assignment, self._results.pop(session.worker_id, None)

    def parameter_applied(self, ack):
        with self._lock:
            key = (ack.worker_id, ack.session_id)
            offer = self._offers.get(key)
            if (
                self._state != "RUNNING"
                or not self._active(*key)
                or offer is None
                or (ack.attempt_id, ack.operation_id, ack.model_version)
                != (
                    self._context.attempt_id,
                    offer[0],
                    offer[1],
                )
            ):
                raise ValueError("Unexpected async parameter ACK")
            del self._offers[key]
            return False

    def admit(self, contribution):
        with self._lock:
            if self._state != "RUNNING":
                raise ContributionRejected(
                    "PROTO_ILLEGAL_MESSAGE_ORDER", "Async admission is closed"
                )
            key = (contribution.worker_id, contribution.session_id)
            assignment = self.pool.assignments.get(contribution.worker_id)
            if not self._active(*key) or assignment is None or key in self._offers:
                raise ContributionRejected(
                    "TRAIN_WRONG_BATCH_ASSIGNMENT", "No acknowledged async assignment"
                )
            before = self._model.snapshot()
            decision = self._async_policy.admit(contribution, assignment, before.model_version)
            if contribution.parameter_manifest_hash != before.parameter_manifest_hash:
                raise ContributionRejected(
                    "TRAIN_MANIFEST_MISMATCH", "Async parameter manifest mismatch"
                )
            applied = decision.learning_rate is not None
            epoch_metrics = self._metrics_for_epoch(assignment.epoch)
            try:
                if applied:
                    self._engine.apply_async_once(
                        contribution, before.model_version, decision.learning_rate
                    )
                self.pool.complete(assignment, applied)
                _accumulate_epoch_contributions(epoch_metrics, [contribution])
            except Exception:
                self._fail("Async update/progress commit failed")
                raise
            self._results[contribution.worker_id] = {
                "operation_id": contribution.operation_id,
                "applied": applied,
                "staleness": decision.staleness,
            }
            self._last_staleness = decision.staleness
            self._last_loss = contribution.loss
            self._event(
                "async.progress",
                {
                    **self._progress(),
                    "worker_id": contribution.worker_id,
                    "operation_id": contribution.operation_id,
                    "staleness": decision.staleness,
                    "applied": applied,
                    "loss": contribution.loss,
                    "sample_count": contribution.sample_count,
                },
            )
            if self._processed_epoch_units(assignment.epoch) == len(self.pool.units):
                self._event(
                    "epoch.metrics.finalized",
                    _compute_epoch_metrics_payload(epoch_metrics, assignment.epoch),
                )
                del self._async_epoch_metrics[assignment.epoch]
            return None, None

    def worker_failed(self, worker_id, session_id):
        with self._lock:
            if self._state in {"FAILED", "ABORTED", "COMPLETED"}:
                return
            self._offers.pop((worker_id, session_id), None)
            self._idle.discard((worker_id, session_id))
            if (
                self._seen_sessions.get(worker_id) == session_id
                and self._disconnected_sessions.get(worker_id) != session_id
            ):
                self._disconnected_sessions[worker_id] = session_id
                self._event(
                    "worker.disconnected", {"worker_id": worker_id, "session_id": str(session_id)}
                )
            if self.pool.reclaim(worker_id, session_id):
                self._idle.clear()  # Reclaimed work wakes surviving idle sessions.

    def _progress(self):
        counts = self.pool.counts
        return {
            "type": "async_sgd",
            **counts,
            "processed_units": counts["applied_units"] + counts["dropped_units"],
            "processed_samples": counts["applied_samples"] + counts["dropped_samples"],
            "target_units": self.pool.target,
            "completed_epochs": self.pool.frontier,
            "model_version": self._model.snapshot().model_version,
            "staleness": self._last_staleness,
            "loss": self._last_loss,
            "active_workers": sum(s.state == SessionState.READY for s in self._registry.snapshot()),
            "epoch_progress": self._epoch_progress(),
        }

    def _active(self, worker_id, session_id):
        return any(
            s.worker_id == worker_id
            and s.session_id == session_id
            and s.state == SessionState.READY
            for s in self._registry.snapshot()
        )

    def snapshot(self):
        with self._lock:
            return {
                "state": self._state,
                "epoch": self.pool.frontier,
                "next_batch_ordinal": 0,
                "current_operation_id": None,
                "model_version": self._model.snapshot().model_version,
                "checkpoint_state": self._checkpoint_state,
                "latest_checkpoint_id": self._latest.snapshot.checkpoint_id
                if self._latest
                else None,
                "strategy_state": self._progress(),
                **self._events.snapshot(),
            }

    def _capture_checkpoint(self):
        self._cursor = RecoveryCursor(self.pool.frontier, 0)
        return replace(
            super()._capture_checkpoint(), async_progress=canonical_json_bytes(self.pool.snapshot())
        )

    def checkpoint(self, *, is_final=False):
        return self.save_checkpoint_for_current_revision(is_final=is_final)

    def save_checkpoint_for_current_revision(self, *, is_final=False):
        with self._checkpoint_io:
            return super().save_checkpoint_for_current_revision(is_final=is_final)

    def has_verified_checkpoint_for_current_revision(self):
        with self._lock:
            return (
                self._latest is not None
                and self._latest.snapshot.model == self._model.snapshot()
                and self._latest.snapshot.async_progress
                == canonical_json_bytes(self.pool.snapshot())
            )

    def _checkpoint_ready(self, is_final):
        return True  # The shared decision lock captures a consistent async recovery cut.

    def run(self, runner, server):
        monitor = HeartbeatMonitor(self._registry, runner._process._heartbeat_timeout)
        while not runner._abort.wait(0.05):
            now = time.monotonic()
            with self._lock:
                if self._state != "RUNNING":
                    raise RuntimeError(f"Async Attempt is {self._state}")
                finished = self.pool.finished
                expired = [
                    (a.worker_id, a.session_id)
                    for a in self.pool.assignments.values()
                    if now - a.started_at >= self.settings["assignment_timeout_seconds"]
                ]
                expired.extend(
                    key
                    for key, offer in self._offers.items()
                    if now - offer[3] >= self.settings["assignment_timeout_seconds"]
                )
                frontier = self.pool.frontier
            if finished:
                self.checkpoint(is_final=True)
                with self._lock:
                    if self._state == "RUNNING":
                        self._transition("COMPLETED")
                return
            for worker_id, session_id in set(expired):
                server.fence(worker_id, session_id)
                self.worker_failed(worker_id, session_id)
            for session in monitor.expired(now):
                server.fence(
                    session.worker_id,
                    session.session_id,
                    observed_heartbeat=session.last_heartbeat_at,
                )
            sessions = [s for s in self._registry.snapshot() if s.state == SessionState.READY]
            if sessions:
                self._zero_since = None
            elif self._zero_since is None:
                self._zero_since = now
            elif now - self._zero_since >= self.settings["reconnect_grace_seconds"]:
                self.fail("WORKER_RECONNECT_TIMEOUT")
                raise TimeoutError("No ready async Worker within reconnect grace")
            for session in sessions:
                offer = self.offer(session, now)
                if offer is not None:
                    server.send_async_offer(session.worker_id, session.session_id, *offer)
            if self._checkpoint_policy.crossed_epoch_boundary(self._last_frontier, frontier):
                self.checkpoint()
            self._last_frontier = frontier
        self.abort()
