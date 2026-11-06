"""Async numerical, recovery and session-fencing oracles."""

import contextlib
import json
import threading
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

from pbl4.common.async_training import resolve_async_training
from pbl4.common.work_unit import WorkUnitRef
from pbl4.runtime.batch_scheduler import RecoveryCursor
from pbl4.runtime.canonical_model import CanonicalModel
from pbl4.runtime.checkpoint import CheckpointManager
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.checkpoint_serializer import TrainingCheckpointSerializer
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.snapshot import CheckpointSnapshot
from pbl4.runtime.synchronization.base import ParameterApplied
from pbl4.runtime.synchronization.context import Member, StrategyContext
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.training_flows.async_sgd import AsyncCoordinator
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.runtime.workload_pool import GlobalWorkUnitPool


def coordinator(tmp_path, *, threshold=0):
    ctx = StrategyContext(
        "job",
        "attempt",
        "contract",
        "async_sgd",
        2,
        "plain_sgd",
        "dataset",
        "b" * 64,
        "c" * 64,
        1,
        2,
        (Member(0, 10), Member(1, 11)),
    )
    registry = WorkerRegistry(ctx.attempt_id, 2, allow_rejoin=True)
    for member in ctx.membership:
        registry.register(member.session_id, 0, member.worker_id)
        for phase in list(SessionState)[1:6]:
            registry.transition(member.worker_id, member.session_id, phase, 0)
    model = CanonicalModel(np.array([10, 20], dtype=np.float32), 0, ctx.parameter_manifest_hash)
    template = CheckpointSnapshot(
        "pending",
        2,
        ctx.job_id,
        ctx.attempt_id,
        ctx.contract_hash,
        "periodic",
        1,
        "async_sgd",
        ctx.dataset_build_id,
        ctx.dataset_manifest_hash,
        "small_cnn",
        "SMALL_CNN_V1",
        0,
        None,
        "plain_sgd",
        "2026-11-04T00:00:00Z",
        model.snapshot(),
        RecoveryCursor(0, 0),
    )
    result = AsyncCoordinator(
        ctx,
        registry,
        create_policy(ctx, learning_rate=0.5, staleness_threshold=threshold),
        model,
        UpdateEngine(model, ctx.attempt_id, "plain_sgd", 0.5),
        None,
        CheckpointPolicy(1),
        CheckpointManager(tmp_path, TrainingCheckpointSerializer()),
        template,
        EventEmitter(ctx.attempt_id, ctx.job_id),
        pool=GlobalWorkUnitPool([WorkUnitRef(0, i, 1) for i in range(3)], 42, 3, 1),
        settings=resolve_async_training({"staleness_threshold": threshold}),
    )
    for _ in range(4):
        result.advance_initialization()
    return result


def offer(c, worker):
    session = c._registry.snapshot()[worker]
    snapshot, operation, assignment, _ = c.offer(session, 0)
    c.parameter_applied(
        ParameterApplied(
            "attempt", session.session_id, worker, operation, 0, snapshot.model_version
        )
    )
    return assignment


def gradient(a):
    return Contribution.from_gradient(
        np.array([2, 4], dtype=np.float32),
        attempt_id="attempt",
        session_id=a.session_id,
        worker_id=a.worker_id,
        operation_id=a.operation_id,
        step_id=None,
        model_version=a.model_version,
        shard_id=a.work_units[0].shard_id,
        batch_id=a.work_units[0].batch_id,
        batch_ordinal=a.operation_id,
        sample_count=1,
        parameter_manifest_hash="c" * 64,
        tensor_id=0,
        compute_ms=1,
    )


def test_atomic_apply_drop_duplicate_and_progress_checkpoint(tmp_path):
    c = coordinator(tmp_path)
    a, b = offer(c, 0), offer(c, 1)
    c.admit(gradient(a))
    first = c.checkpoint()
    assert c.has_verified_checkpoint_for_current_revision()
    c.admit(gradient(b))
    assert not c.has_verified_checkpoint_for_current_revision()
    second = c.checkpoint()
    np.testing.assert_array_equal(c._model.snapshot().parameters, [9, 18])
    assert second.snapshot.model.model_version == first.snapshot.model.model_version == 1
    assert second.snapshot.async_progress != first.snapshot.async_progress
    assert c.snapshot()["strategy_state"]["dropped_units"] == 1
    with pytest.raises(ValueError):
        c.admit(gradient(b))
    restored = GlobalWorkUnitPool(c.pool.units, 42, 3, 1)
    restored.restore(json.loads(second.snapshot.async_progress))
    assert restored.counts == c.pool.counts


def test_old_session_cannot_commit_or_reclaim_replacement(tmp_path):
    c = coordinator(tmp_path)
    old = offer(c, 0)
    c.worker_failed(0, 10)
    c._registry.transition(0, 10, SessionState.DISCONNECTED, 1)
    c._registry.register(30, 2, 0)
    for phase in list(SessionState)[1:6]:
        c._registry.transition(0, 30, phase, 2)
    replacement = offer(c, 0)
    assert replacement.indices == old.indices
    c.worker_failed(0, 10)
    assert c.pool.assignments[0] == replacement
    with pytest.raises(ValueError):
        c.admit(gradient(old))
    c.admit(gradient(replacement))
    c.abort()
    with pytest.raises(ValueError):
        c.admit(gradient(replacement))


def test_update_and_reclaim_race_preserves_partition(tmp_path):
    c = coordinator(tmp_path)
    a = offer(c, 0)
    gate = threading.Barrier(2)

    def submit():
        gate.wait()
        with contextlib.suppress(ValueError):
            c.admit(gradient(a))

    thread = threading.Thread(target=submit)
    thread.start()
    gate.wait()
    c.worker_failed(0, 10)
    thread.join(2)
    assert not thread.is_alive()
    assert c.pool.counts["applied_units"] + len(c.pool.remaining) == c.pool.issued
    assert c._model.snapshot().model_version == c.pool.counts["applied_units"]


def test_zero_ready_workers_exhaust_grace_without_model_mutation(tmp_path, monkeypatch):
    import pbl4.runtime.training_flows.async_sgd as flow

    c = coordinator(tmp_path)
    for s in c._registry.snapshot():
        c._registry.transition(s.worker_id, s.session_id, SessionState.DISCONNECTED, 1)
    c.settings["reconnect_grace_seconds"] = 1
    clock = iter(range(10))
    monkeypatch.setattr(flow, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    runner = SimpleNamespace(
        _abort=threading.Event(), _process=SimpleNamespace(_heartbeat_timeout=100)
    )
    with pytest.raises(TimeoutError, match="reconnect grace"):
        c.run(runner, SimpleNamespace())
    assert c.snapshot()["state"] == "FAILED"
    assert c._model.snapshot().model_version == 0


def test_assignment_timeout_fences_worker_even_with_fresh_heartbeat(tmp_path, monkeypatch):
    import pbl4.runtime.training_flows.async_sgd as flow

    c = coordinator(tmp_path)
    assignment = offer(c, 0)
    c._registry.heartbeat(0, 10, 10)
    c.settings["assignment_timeout_seconds"] = 1
    monkeypatch.setattr(flow, "time", SimpleNamespace(monotonic=lambda: 10))
    calls = []

    def fence(worker, session):
        calls.append((worker, session))
        c._registry.transition(worker, session, SessionState.DISCONNECTED, 10)
        c.worker_failed(worker, session)

    aborts = iter([False, True])
    runner = SimpleNamespace(
        _abort=SimpleNamespace(wait=lambda _: next(aborts)),
        _process=SimpleNamespace(_heartbeat_timeout=100),
    )
    c.run(runner, SimpleNamespace(fence=fence, send_async_offer=lambda *args: None))
    assert calls == [(0, 10)]
    assert set(assignment.indices) <= c.pool.remaining
    assert c._model.snapshot().model_version == 0


def test_checkpoint_policy_detects_skipped_epoch_milestones():
    policy = CheckpointPolicy(5)
    assert not policy.crossed_epoch_boundary(0, 4)
    assert policy.crossed_epoch_boundary(4, 6)
    assert policy.crossed_epoch_boundary(0, 12)
    assert not policy.crossed_epoch_boundary(12, 12)


def test_idle_survivor_wakes_for_reclaimed_work_and_finishes(tmp_path):
    c = coordinator(tmp_path)
    abandoned = offer(c, 0)
    while True:
        assignment = offer(c, 1)
        if assignment is None:
            break
        c.admit(gradient(assignment))
    assert not c.pool.finished
    c.worker_failed(0, abandoned.session_id)
    reclaimed = offer(c, 1)
    assert reclaimed.indices == abandoned.indices
    c.admit(gradient(reclaimed))
    assert c.pool.finished
    assert not c.accepts_workers
    assert c.pool.counts["applied_units"] + c.pool.counts["dropped_units"] == c.pool.target


def test_disconnect_after_commit_does_not_requeue_processed_work(tmp_path):
    c = coordinator(tmp_path)
    assignment = offer(c, 0)
    c.admit(gradient(assignment))
    c.worker_failed(0, assignment.session_id)
    next_assignment = offer(c, 1)
    assert not set(next_assignment.indices).intersection(assignment.indices)
    assert c.pool.counts["applied_units"] == 1


def test_async_epoch_metrics_follow_occurrences_across_overlap_and_stale_drop(tmp_path):
    c = coordinator(tmp_path, threshold=0)
    slow = offer(c, 0)
    while True:
        assignment = offer(c, 1)
        if assignment.epoch == 2:
            break
        loss = 2.0 if assignment.epoch == 0 else 4.0
        c.admit(replace(gradient(assignment), loss=loss, correct_count=1))
    summaries = [e.details for e in c._events.peek() if e.event_type == "epoch.metrics.finalized"]
    assert [e["epoch_index"] for e in summaries] == [1]
    assert summaries[0]["training_loss"] == 4.0
    assert summaries[0]["training_accuracy"] == 100.0
    progress = c.snapshot()["strategy_state"]["epoch_progress"]
    assert progress["epoch_index"] == 0
    assert progress["processed_units"] == 2
    assert progress["target_units"] == 3
    assert progress["training_loss"] == 2.0
    c.admit(replace(gradient(slow), loss=8.0, correct_count=0))
    assert c.snapshot()["strategy_state"]["dropped_units"] == 1
    summaries = [e.details for e in c._events.peek() if e.event_type == "epoch.metrics.finalized"]
    assert [e["epoch_index"] for e in summaries] == [1, 0]
    assert summaries[-1]["training_loss"] == 4.0
    assert summaries[-1]["training_accuracy"] == pytest.approx(200 / 3)
    assert summaries[-1]["sample_count"] == 3
    with pytest.raises(ValueError):
        c.admit(gradient(slow))
    assert len([e for e in c._events.peek() if e.event_type == "epoch.metrics.finalized"]) == 2


def test_async_epoch_metrics_are_sample_weighted_and_rejoin_does_not_double_count(tmp_path):
    c = coordinator(tmp_path, threshold=100)
    c.pool = GlobalWorkUnitPool([WorkUnitRef(0, i, i + 1) for i in range(3)], 42, 1, 2)
    old = offer(c, 0)
    c.worker_failed(0, old.session_id)
    c._registry.transition(0, old.session_id, SessionState.DISCONNECTED, 1)
    c._registry.register(30, 2, 0)
    for phase in list(SessionState)[1:6]:
        c._registry.transition(0, 30, phase, 2)
    assignment = offer(c, 0)
    total_loss = total_samples = total_correct = 0
    while assignment is not None:
        samples = sum(u.sample_count for u in assignment.work_units)
        loss = float(samples)
        total_loss += loss * samples
        total_samples += samples
        total_correct += 1
        c.admit(replace(gradient(assignment), sample_count=samples, loss=loss, correct_count=1))
        assignment = offer(c, 0)
    summary = [e.details for e in c._events.peek() if e.event_type == "epoch.metrics.finalized"]
    assert len(summary) == 1
    assert summary[0]["sample_count"] == total_samples == 6
    assert summary[0]["training_loss"] == total_loss / total_samples
    assert summary[0]["training_accuracy"] == 100 * total_correct / total_samples
    assert c.snapshot()["strategy_state"]["epoch_progress"] is None
    assert not c._async_epoch_metrics


def test_async_partial_checkpoint_resume_does_not_fabricate_missing_epoch_measurements(tmp_path):
    c = coordinator(tmp_path, threshold=100)
    first = offer(c, 0)
    c.admit(replace(gradient(first), loss=2.0, correct_count=1))
    restored = coordinator(tmp_path / "restored", threshold=100)
    restored.pool.restore(c.pool.snapshot())
    while restored.pool.frontier == 0:
        assignment = offer(restored, 0)
        restored.admit(replace(gradient(assignment), loss=3.0, correct_count=1))
    first_summary = next(
        e.details for e in restored._events.peek() if e.event_type == "epoch.metrics.finalized"
    )
    assert first_summary["sample_count"] == 3
    assert first_summary["training_loss"] is None
    assert first_summary["training_accuracy"] is None
    while restored.pool.frontier == 1:
        assignment = offer(restored, 0)
        restored.admit(replace(gradient(assignment), loss=5.0, correct_count=1))
    second_summary = [
        e.details for e in restored._events.peek() if e.event_type == "epoch.metrics.finalized"
    ][-1]
    assert second_summary["epoch_index"] == 1
    assert second_summary["training_loss"] == 5.0
    assert second_summary["training_accuracy"] == 100.0


def test_epoch_progress_survives_backend_response_serialization_and_old_runtime_is_supported():
    from pbl4.management_backend.schemas.attempt import AttemptSnapshot
    from pbl4.management_backend.schemas.runtime import RuntimeSnapshot

    payload = {
        "type": "async_sgd",
        "completed_epochs": 0,
        "epoch_progress": {
            "epoch_index": 0,
            "processed_units": 1,
            "target_units": 3,
            "sample_count": 256,
            "training_loss": 0.0,
            "training_accuracy": 0.5,
        },
    }
    attempt = AttemptSnapshot(attempt_id="attempt", state="RUNNING", strategy_state=payload)
    runtime = RuntimeSnapshot(strategy_state=payload)
    assert attempt.model_dump()["strategy_state"]["epoch_progress"] == payload["epoch_progress"]
    assert runtime.model_dump()["strategy_state"]["epoch_progress"] == payload["epoch_progress"]
    old_runtime = RuntimeSnapshot(strategy_state={"type": "async_sgd"})
    assert old_runtime.strategy_state.epoch_progress is None


def test_checkpoint_writes_cannot_publish_out_of_order(tmp_path, monkeypatch):
    c = coordinator(tmp_path)
    entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
    writes = []
    original = c._checkpoints.write

    def write(snapshot):
        writes.append(snapshot)
        if len(writes) == 1:
            entered.set()
            assert release.wait(2)
        return original(snapshot)

    monkeypatch.setattr(c._checkpoints, "write", write)
    first = threading.Thread(target=c.checkpoint)

    def second_save():
        second_started.set()
        c.save_checkpoint_for_current_revision()

    second = threading.Thread(target=second_save)
    first.start()
    assert entered.wait(2)
    c.admit(gradient(offer(c, 0)))
    second.start()
    assert second_started.wait(2)
    assert len(writes) == 1
    release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert c._latest.snapshot == writes[-1]
    assert c._latest.snapshot.model.model_version == 1
