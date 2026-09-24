"""Attempt/Step progression with separate synchronization and durability gates."""

from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock
from uuid import uuid4

from pbl4.runtime.aggregator import GradientAggregator
from pbl4.runtime.batch_scheduler import BatchScheduler, RecoveryCursor
from pbl4.runtime.canonical_model import CanonicalModel, ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointManager, CompleteCheckpoint
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.gradient_store import GradientStore
from pbl4.runtime.snapshot import CheckpointSnapshot
from pbl4.runtime.synchronization.base import (
    AdmissionCode,
    AdmissionDecision,
    ParameterApplied,
    SynchronizationPolicy,
)
from pbl4.runtime.synchronization.context import OperationContext, StrategyContext
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry


def _now() -> str:
    return datetime.now(UTC).isoformat()


class Coordinator:
    """Single Attempt owner; no socket/HTTP/filesystem calls under the state lock.

    Lock order: Coordinator -> policy/registry/store/update/model/emitter.
    None of those owners calls back into Coordinator. CheckpointManager executes
    outside this lock; late I/O completion cannot resurrect a terminal Attempt.
    """

    def __init__(
        self,
        context: StrategyContext,
        registry: WorkerRegistry,
        policy: SynchronizationPolicy,
        model: CanonicalModel,
        engine: UpdateEngine,
        scheduler: BatchScheduler,
        checkpoint_policy: CheckpointPolicy,
        checkpoints: CheckpointManager,
        checkpoint_context: CheckpointSnapshot,
        events: EventEmitter,
        cursor: RecoveryCursor | None = None,
    ):
        if (
            checkpoint_context.job_id != context.job_id
            or checkpoint_context.created_by_attempt_id != context.attempt_id
            or checkpoint_context.contract_hash != context.contract_hash
            or checkpoint_context.dataset_build_id != context.dataset_build_id
            or checkpoint_context.dataset_manifest_hash != context.dataset_manifest_hash
            or checkpoint_context.checkpoint_policy != checkpoint_policy.checkpoint_policy
            or model.snapshot().parameter_manifest_hash != context.parameter_manifest_hash
        ):
            raise ValueError("Checkpoint/Attempt contract mismatch")
        self._context = context
        self._registry = registry
        self._policy = policy
        self._model = model
        self._engine = engine
        self._scheduler = scheduler
        self._checkpoint_policy = checkpoint_policy
        self._checkpoints = checkpoints
        self._checkpoint_context = checkpoint_context
        self._events = events
        self._cursor = cursor if cursor is not None else RecoveryCursor(0, 0)
        self._lock = RLock()
        self._state = "CREATED"
        self._step_state: str | None = None
        self._operation: OperationContext | None = None
        self._store = GradientStore()
        self._aggregator = GradientAggregator()
        self._latest: CompleteCheckpoint | None = None
        self._checkpoint_state: str | None = None
        self._milestones: dict[str, str] = {}

    def _event(self, event_type: str, details: dict[str, object], severity: str = "INFO") -> None:
        self._events.emit(event_type, details, _now(), "coordinator", severity)

    def _transition(self, state: str) -> None:
        previous = self._state
        self._state = state
        self._event("attempt.state_changed", {"previous_state": previous, "state": state})

    def advance_initialization(self) -> str:
        """Advance only the next startup phase whose observed prerequisites hold."""
        with self._lock:
            sessions = self._registry.snapshot()
            if self._state == "CREATED":
                self._transition("WAITING_WORKERS")
            elif self._state == "WAITING_WORKERS":
                actual = {(s.worker_id, s.session_id) for s in sessions}
                expected = {(m.worker_id, m.session_id) for m in self._context.membership}
                if actual != expected or any(
                    s.state
                    in (SessionState.CONNECTING, SessionState.DISCONNECTED, SessionState.FAILED)
                    for s in sessions
                ):
                    raise ValueError("Registered membership is incomplete")
                self._transition("PROVISIONING")
            elif self._state == "PROVISIONING":
                if not sessions or any(s.state != SessionState.SHARD_READY for s in sessions):
                    raise ValueError("All shards must be verified ready")
                self._transition("INITIALIZING")
            elif self._state == "INITIALIZING":
                membership = self._registry.freeze_membership()
                if set(membership) != set(self._context.membership):
                    raise ValueError("Model-ready membership differs from contract")
                self._transition("RUNNING")
            else:
                raise ValueError("Attempt is not initializing")
            return self._state

    def open_step(self) -> OperationContext:
        """Open the V1 Step projection after both previous progression gates."""
        with self._lock:
            if self._state != "RUNNING" or self._step_state not in (None, "COMMITTED"):
                raise ValueError("Attempt/Step progression is blocked")
            assignments = self._scheduler.assignments(self._cursor)
            step = 0 if self._operation is None else self._operation.step_id + 1
            operation = OperationContext(
                step,
                step,
                self._cursor.epoch,
                self._cursor.next_batch_ordinal,
                self._model.snapshot().model_version,
                assignments,
            )
            self._policy.open_operation(operation)
            self._operation = operation
            self._step_state = "COLLECTING_GRADIENTS"
            self._checkpoint_state = None
            self._milestones = {"started_at": _now()}
            self._event(
                "step.started",
                {
                    "step_id": step,
                    "operation_id": operation.operation_id,
                    "epoch": operation.epoch,
                    "batch_ordinal": operation.batch_ordinal,
                    "input_model_version": operation.input_model_version,
                    "training_strategy": self._context.training_strategy,
                    "assignments": [
                        {
                            "worker_id": item.worker_id,
                            "shard_id": item.shard_id,
                            "batch_id": item.batch_id,
                            "batch_ordinal": item.batch_ordinal,
                            "sample_count": item.sample_count,
                        }
                        for item in assignments
                    ],
                },
            )
            return operation

    def admit(self, contribution: Contribution) -> tuple[AdmissionDecision, ModelSnapshot | None]:
        with self._lock:
            if self._state != "RUNNING" or self._step_state != "COLLECTING_GRADIENTS":
                return AdmissionDecision(
                    AdmissionCode.REJECT_STRATEGY_STATE, "Step is closed"
                ), None
            decision = self._policy.admit(contribution)
            if decision.code == AdmissionCode.FATAL_STRATEGY_ERROR:
                self._fail(decision.reason)
                return decision, None
            if decision.code != AdmissionCode.ACCEPT:
                return decision, None
            self._store.record(contribution, decision)
            plan = decision.update_plan
            if plan is None:
                return decision, None
            self._step_state = "AGGREGATING"
        try:
            aggregate = self._aggregator.aggregate(plan)
            with self._lock:
                if self._state != "RUNNING":
                    return decision, None
                self._step_state = "UPDATING"
                published = self._engine.apply_once(plan, aggregate)
                self._milestones["update_completed_at"] = _now()
                self._policy.mark_update_published(plan, published.model_version)
                self._step_state = "WAITING_PARAMETER_APPLIED"
                self._event(
                    "model.updated",
                    {
                        "step_id": plan.step_id,
                        "operation_id": plan.operation_id,
                        "input_model_version": plan.input_model_version,
                        "output_model_version": published.model_version,
                        "total_sample_count": plan.total_sample_count,
                        "contributions": [
                            {
                                "worker_id": item.worker_id,
                                "session_id": item.session_id,
                                "shard_id": item.shard_id,
                                "batch_id": item.batch_id,
                                "batch_ordinal": item.batch_ordinal,
                                "sample_count": item.sample_count,
                                "tensor_id": item.tensor_id,
                                "parameter_manifest_hash": item.parameter_manifest_hash,
                            }
                            for item in plan.contributions
                        ],
                    },
                )
                # Caller sends this immutable snapshot through DTP outside our lock.
                return decision, published
        except Exception:
            with self._lock:
                if self._state == "RUNNING":
                    self._fail("Canonical update failed")
            raise

    def parameter_applied(self, ack: ParameterApplied) -> bool:
        """Return True once when the caller should request the durability operation."""
        with self._lock:
            if self._state != "RUNNING" or self._step_state != "WAITING_PARAMETER_APPLIED":
                return False
            decision = self._policy.ack_parameter_applied(ack)
            if decision.code == AdmissionCode.FATAL_STRATEGY_ERROR:
                self._fail(decision.reason)
                return False
            if decision.code != AdmissionCode.ACCEPT:
                return False
            self._event(
                "parameter.applied",
                {
                    "worker_id": ack.worker_id,
                    "session_id": ack.session_id,
                    "operation_id": ack.operation_id,
                    "step_id": ack.step_id,
                    "model_version": ack.model_version,
                },
            )
            if self._policy.synchronization_complete:
                self._milestones["synchronization_completed_at"] = _now()
                return True
            return False

    def checkpoint(self) -> CompleteCheckpoint | None:
        with self._lock:
            if (
                self._state != "RUNNING"
                or self._step_state != "WAITING_PARAMETER_APPLIED"
                or not self._checkpoint_policy.requires_checkpoint(
                    update_completed="update_completed_at" in self._milestones,
                    synchronization_complete=self._policy.synchronization_complete,
                )
            ):
                raise ValueError("Checkpoint safe boundary has not been reached")
            operation = self._operation
            assert operation is not None
            next_cursor = self._scheduler.next_cursor(self._cursor)
            snapshot = replace(
                self._checkpoint_context,
                checkpoint_id=uuid4().hex,
                model=self._model.snapshot(),
                recovery_cursor=next_cursor,
                source_operation_id=operation.operation_id,
                source_step_id=operation.step_id,
                created_at=_now(),
            )
            self._step_state = "CHECKPOINTING"
            self._checkpoint_state = "WRITING"
            self._event(
                "checkpoint.started",
                {
                    "checkpoint_id": snapshot.checkpoint_id,
                    "source_operation_id": snapshot.source_operation_id,
                    "source_step_id": snapshot.source_step_id,
                    "model_version": snapshot.model.model_version,
                    "recovery_cursor": {
                        "epoch": snapshot.recovery_cursor.epoch,
                        "next_batch_ordinal": snapshot.recovery_cursor.next_batch_ordinal,
                    },
                    "contract_hash": snapshot.contract_hash,
                    "dataset_build_id": snapshot.dataset_build_id,
                    "dataset_manifest_hash": snapshot.dataset_manifest_hash,
                    "parameter_manifest_hash": snapshot.model.parameter_manifest_hash,
                    "checkpoint_policy": snapshot.checkpoint_policy,
                    "checkpoint_policy_version": snapshot.checkpoint_policy_version,
                    "created_at": snapshot.created_at,
                },
            )
        attempts = 0
        while self._checkpoint_policy.may_retry(attempts):
            with self._lock:
                if self._state != "RUNNING":
                    return None
            attempts += 1
            try:
                complete = self._checkpoints.write(snapshot)
            except Exception:
                with self._lock:
                    if self._state != "RUNNING":
                        return None
                    if not self._checkpoint_policy.may_retry(attempts):
                        self._checkpoint_state = "FAILED"
                        self._event(
                            "checkpoint.failed", {"checkpoint_id": snapshot.checkpoint_id}, "ERROR"
                        )
                        self._fail("Checkpoint attempts exhausted")
                        return None
                continue
            with self._lock:
                if (
                    self._state != "RUNNING"
                    or self._step_state != "CHECKPOINTING"
                    or self._operation != operation
                    or not self._policy.synchronization_complete
                ):
                    return None
                self._latest = complete
                self._checkpoint_state = "COMPLETE"
                self._milestones["checkpoint_completed_at"] = _now()
                if not self._checkpoint_policy.allows_commit(
                    synchronization_complete=self._policy.synchronization_complete,
                    checkpoint_state=self._checkpoint_state,
                ):
                    raise ValueError("Durability gate inconsistency")
                self._step_state = "COMMITTED"
                self._milestones["committed_at"] = _now()
                self._cursor = next_cursor
                self._store.discard(self._context.attempt_id, operation.operation_id)
                self._event(
                    "checkpoint.saved",
                    {
                        "checkpoint_id": snapshot.checkpoint_id,
                        "source_operation_id": snapshot.source_operation_id,
                        "source_step_id": snapshot.source_step_id,
                        "model_version": snapshot.model.model_version,
                        "model_path": f"{complete.directory.name}/model.bin",
                        "metadata_path": f"{complete.directory.name}/checkpoint.json",
                        "model_sha256": complete.model_sha256,
                        "metadata_sha256": complete.metadata_sha256,
                        "artifact_size_bytes": complete.model_size + complete.metadata_size,
                        "recovery_cursor": {
                            "epoch": next_cursor.epoch,
                            "next_batch_ordinal": next_cursor.next_batch_ordinal,
                        },
                        "checkpoint_completed_at": self._milestones["checkpoint_completed_at"],
                        "committed_at": self._milestones["committed_at"],
                    },
                )
                return complete
        raise AssertionError("Checkpoint policy allowed no attempt")

    def _fail(self, reason: str) -> None:
        self._policy.cleanup()
        if self._operation:
            self._store.discard(self._context.attempt_id, self._operation.operation_id)
        self._transition("FAILED")
        self._event("attempt.failed", {"reason": reason}, "ERROR")

    def worker_failed(self, worker_id: int, session_id: int) -> None:
        with self._lock:
            if self._state in ("COMPLETED", "FAILED", "ABORTED"):
                return
            decision = self._policy.worker_failed(worker_id, session_id)
            if decision.code == AdmissionCode.FATAL_STRATEGY_ERROR:
                self._fail(decision.reason)

    def fail(self, reason: str) -> None:
        """Fail the Attempt for a Runtime-owned fatal condition."""
        with self._lock:
            if self._state in ("COMPLETED", "FAILED", "ABORTED"):
                return
            self._fail(reason)

    def abort(self) -> None:
        with self._lock:
            if self._state in ("COMPLETED", "FAILED", "ABORTED"):
                return
            self._policy.cleanup()
            if self._operation:
                self._store.discard(self._context.attempt_id, self._operation.operation_id)
            self._transition("ABORTED")

    def heartbeat(self, worker_id: int, session_id: int, now: float) -> None:
        with self._lock:
            self._registry.heartbeat(worker_id, session_id, now)

    def heartbeat_timeout(self, worker_id: int, session_id: int, observed_heartbeat: float) -> None:
        """Revalidate monitor observations before applying failure semantics."""
        with self._lock:
            current = next((s for s in self._registry.snapshot() if s.worker_id == worker_id), None)
            if current is None or current.session_id != session_id:
                return
            if current.last_heartbeat_at != observed_heartbeat:
                return
            self.worker_failed(worker_id, session_id)

    def complete(self) -> None:
        with self._lock:
            if self._state != "RUNNING" or self._step_state != "COMMITTED":
                raise ValueError("Attempt still has uncommitted work")
            try:
                self._scheduler.assignments(self._cursor)
            except StopIteration:
                self._transition("COMPLETING")
                self._policy.cleanup()
                self._transition("COMPLETED")
            else:
                raise ValueError("Training schedule has remaining work")

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "attempt_id": self._context.attempt_id,
                "job_id": self._context.job_id,
                "current_operation_id": self._operation.operation_id if self._operation else None,
                "membership": tuple(
                    {"worker_id": s.worker_id, "session_id": s.session_id, "state": s.state.value}
                    for s in self._registry.snapshot()
                ),
                "state": self._state,
                "training_strategy": self._context.training_strategy,
                "step_state": self._step_state,
                "model_version": self._model.snapshot().model_version,
                "epoch": self._cursor.epoch,
                "next_batch_ordinal": self._cursor.next_batch_ordinal,
                "checkpoint_state": self._checkpoint_state,
                "latest_checkpoint_id": self._latest.snapshot.checkpoint_id
                if self._latest
                else None,
                "strategy_state": self._policy.snapshot(),
                "milestones": dict(self._milestones),
                **self._events.snapshot(),
            }
