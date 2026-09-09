"""Coordinator semantic integration. Parameter application is simulated ONLY here."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import numpy as np
import pytest

from pbl4.runtime.batch_scheduler import BatchScheduler
from pbl4.runtime.canonical_model import CanonicalModel
from pbl4.runtime.checkpoint import CheckpointManager
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.coordinator import Coordinator
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.synchronization.base import ParameterApplied
from pbl4.runtime.synchronization.context import BatchAssignment, Member, StrategyContext
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from tests.test_checkpoint_mechanics import TestOnlySerializer, snapshot


def running(tmp_path):
    ctx = StrategyContext(
        "job",
        "attempt",
        "contract",
        "strict_bsp",
        3,
        "plain_sgd",
        "dataset",
        "dataset-hash",
        "manifest",
        1,
        2,
        tuple(Member(w, w + 1) for w in range(3)),
    )
    registry = WorkerRegistry("attempt", 3)
    for w in range(3):
        registry.register(w + 1, 0, w)
    model = CanonicalModel(np.array([10, 20], dtype=np.float32), 7, "manifest")
    batches = tuple(BatchAssignment(w, w, b, b, [1, 2, 1][w]) for w in range(3) for b in range(2))
    manager = CheckpointManager(tmp_path, TestOnlySerializer())
    coordinator = Coordinator(
        ctx,
        registry,
        create_policy(ctx),
        model,
        UpdateEngine(model, "attempt", "plain_sgd", 0.5),
        BatchScheduler(batches, 42, 1),
        CheckpointPolicy(),
        manager,
        snapshot(),
        EventEmitter("attempt", "job", capacity=2),
    )
    assert coordinator.advance_initialization() == "WAITING_WORKERS"
    with pytest.raises(ValueError):
        coordinator.advance_initialization()
    for w in range(3):
        registry.transition(w, w + 1, SessionState.REGISTERING, 0)
    assert coordinator.advance_initialization() == "PROVISIONING"
    for w in range(3):
        registry.transition(w, w + 1, SessionState.PROVISIONING, 0)
        registry.transition(w, w + 1, SessionState.SHARD_READY, 0)
    assert coordinator.advance_initialization() == "INITIALIZING"
    for w in range(3):
        registry.transition(w, w + 1, SessionState.MODEL_SYNCING, 0)
        registry.transition(w, w + 1, SessionState.READY, 0)
    assert coordinator.advance_initialization() == "RUNNING"
    return coordinator, manager


def contribution(op, w):
    assigned = op.assignments[w]
    return Contribution.from_gradient(
        np.array([[1, 1], [3, 3], [5, 5]][w], dtype=np.float32),
        attempt_id="attempt",
        session_id=w + 1,
        worker_id=w,
        operation_id=op.operation_id,
        step_id=op.step_id,
        model_version=op.input_model_version,
        shard_id=assigned.shard_id,
        batch_id=assigned.batch_id,
        batch_ordinal=assigned.batch_ordinal,
        sample_count=assigned.sample_count,
        parameter_manifest_hash="manifest",
        tensor_id=w,
    )


def ack(op, w):
    return ParameterApplied(
        "attempt", w + 1, w, op.operation_id, op.step_id, op.input_model_version + 1
    )


def updated(coordinator):
    op = coordinator.open_step()
    for w in range(3):
        _, output = coordinator.admit(contribution(op, w))
        if w < 2:
            assert output is None
    assert output is not None
    return op, output


def applied(coordinator, op):
    for w in range(3):
        assert coordinator.parameter_applied(ack(op, w)) == (w == 2)


def test_full_semantic_pipeline_and_completion(tmp_path):
    coordinator, manager = running(tmp_path)
    op, output = updated(coordinator)
    assert op.step_id == 0 and op.input_model_version == 7
    assert output.model_version == 8
    np.testing.assert_array_equal(output.parameters, [8.5, 18.5])
    with pytest.raises(ValueError):
        coordinator.open_step()
    with pytest.raises(ValueError):
        coordinator.checkpoint()
    applied(coordinator, op)
    assert "synchronization_completed_at" in coordinator.snapshot()["milestones"]
    assert "committed_at" not in coordinator.snapshot()["milestones"]
    complete = coordinator.checkpoint()
    assert manager.verify(complete).model.model_version == 8
    state = coordinator.snapshot()
    assert state["state"] == "RUNNING"
    assert state["step_state"] == "COMMITTED"
    assert list(state["milestones"]) == [
        "started_at",
        "update_completed_at",
        "synchronization_completed_at",
        "checkpoint_completed_at",
        "committed_at",
    ]
    op2, _ = updated(coordinator)
    assert op2.step_id == 1 and op2.input_model_version == 8
    assert op2.assignments[0].batch_id != op.assignments[0].batch_id
    applied(coordinator, op2)
    coordinator.checkpoint()
    coordinator.complete()
    assert coordinator.snapshot()["state"] == "COMPLETED"


@pytest.mark.parametrize("after_update", [False, True])
def test_worker_disconnect_fail_stops_without_commit(tmp_path, after_update):
    coordinator, _ = running(tmp_path)
    if after_update:
        updated(coordinator)
    else:
        op = coordinator.open_step()
        coordinator.admit(contribution(op, 0))
    coordinator.worker_failed(1, 2)
    assert coordinator.snapshot()["state"] == "FAILED"
    assert coordinator.snapshot()["step_state"] != "COMMITTED"
    with pytest.raises(ValueError):
        coordinator.open_step()


def test_retry_does_not_rerun_update_and_preserves_previous_complete(tmp_path, monkeypatch):
    coordinator, manager = running(tmp_path)
    op, _ = updated(coordinator)
    applied(coordinator, op)
    previous = coordinator.checkpoint()
    op, _ = updated(coordinator)
    applied(coordinator, op)
    attempts = []

    def fail(snapshot):
        attempts.append(snapshot)
        state = coordinator.snapshot()
        assert state["state"] == "RUNNING"
        assert state["step_state"] == "CHECKPOINTING"
        assert state["checkpoint_state"] == "WRITING"
        assert state["model_version"] == 9
        with pytest.raises(ValueError):
            coordinator.open_step()
        raise OSError("disk unavailable")

    monkeypatch.setattr(manager, "write", fail)
    assert coordinator.checkpoint() is None
    assert len(attempts) == 3 and all(s is attempts[0] for s in attempts)
    assert coordinator.snapshot()["state"] == "FAILED"
    assert coordinator.snapshot()["model_version"] == 9
    assert manager.verify(previous).model.model_version == 8


def test_abort_during_checkpoint_cannot_commit_or_resurrect(tmp_path, monkeypatch):
    coordinator, manager = running(tmp_path)
    op, _ = updated(coordinator)
    applied(coordinator, op)
    entered, release = Event(), Event()
    original = manager.write

    def delayed(snapshot):
        entered.set()
        assert release.wait(5)
        return original(snapshot)

    monkeypatch.setattr(manager, "write", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(coordinator.checkpoint)
        assert entered.wait(5)
        aborting = pool.submit(coordinator.abort)
        try:
            aborting.result(timeout=2)
        finally:
            release.set()
        # Physical write may have completed, but Attempt was aborted → must NOT be published
        assert writing.result(timeout=5) is None
    assert coordinator.snapshot()["state"] == "ABORTED"
    assert coordinator.snapshot()["step_state"] != "COMMITTED"
    assert "committed_at" not in coordinator.snapshot()["milestones"]


def test_abort_during_aggregation_prevents_canonical_update(tmp_path, monkeypatch):
    coordinator, _ = running(tmp_path)
    op = coordinator.open_step()
    coordinator.admit(contribution(op, 0))
    coordinator.admit(contribution(op, 1))
    entered, release = Event(), Event()
    original = coordinator._aggregator.aggregate

    def delayed(plan):
        entered.set()
        assert release.wait(5)
        return original(plan)

    monkeypatch.setattr(coordinator._aggregator, "aggregate", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        updating = pool.submit(coordinator.admit, contribution(op, 2))
        assert entered.wait(5)
        coordinator.abort()
        release.set()
        assert updating.result(timeout=5)[1] is None
    assert coordinator.snapshot()["state"] == "ABORTED"
    assert coordinator.snapshot()["model_version"] == 7


def test_final_ack_and_timeout_race(tmp_path):
    coordinator, _ = running(tmp_path)
    op, _ = updated(coordinator)
    coordinator.parameter_applied(ack(op, 0))
    coordinator.parameter_applied(ack(op, 1))
    start = Barrier(2)

    def finish():
        start.wait(timeout=5)
        return coordinator.parameter_applied(ack(op, 2))

    def timeout():
        start.wait(timeout=5)
        coordinator.heartbeat_timeout(2, 3, 0)

    with ThreadPoolExecutor(max_workers=2) as pool:
        final_ack = pool.submit(finish)
        failure = pool.submit(timeout)
        final_ack.result(timeout=5)
        failure.result(timeout=5)
    assert coordinator.snapshot()["state"] == "FAILED"
    assert coordinator.snapshot()["step_state"] != "COMMITTED"


def test_fresh_transfer_progress_invalidates_old_timeout(tmp_path):
    coordinator, _ = running(tmp_path)
    coordinator.heartbeat(0, 1, 20)
    coordinator.heartbeat_timeout(0, 1, 0)
    assert coordinator.snapshot()["state"] == "RUNNING"


def test_abort_linearizes_after_inflight_canonical_update(tmp_path, monkeypatch):
    coordinator, _ = running(tmp_path)
    op = coordinator.open_step()
    coordinator.admit(contribution(op, 0))
    coordinator.admit(contribution(op, 1))
    entered, release = Event(), Event()
    original = coordinator._engine._updater.update

    def delayed(*args):
        entered.set()
        assert release.wait(5)
        return original(*args)

    monkeypatch.setattr(coordinator._engine._updater, "update", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        updating = pool.submit(coordinator.admit, contribution(op, 2))
        assert entered.wait(5)
        aborting = pool.submit(coordinator.abort)
        release.set()
        updating.result(timeout=5)
        aborting.result(timeout=5)
    state = coordinator.snapshot()
    assert state["state"] == "ABORTED"
    assert state["model_version"] == 8
    assert state["step_state"] != "COMMITTED"
    with pytest.raises(ValueError):
        coordinator.checkpoint()


# ── Issue A: Checkpoint / Abort + Failure race tests ─────────────────────────


def test_a1_abort_during_checkpoint_write_does_not_publish(tmp_path, monkeypatch):
    """A1: abort() during blocking write → checkpoint not published as latest."""
    coordinator, manager = running(tmp_path)
    op, _ = updated(coordinator)
    applied(coordinator, op)
    before = coordinator.snapshot()
    entered, release = Event(), Event()
    original = manager.write

    def delayed(snapshot):
        entered.set()
        assert release.wait(5)
        return original(snapshot)

    monkeypatch.setattr(manager, "write", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(coordinator.checkpoint)
        assert entered.wait(5)
        pool.submit(coordinator.abort).result(timeout=2)
        release.set()
        result = writing.result(timeout=5)
    # Physical file may exist but must NOT be the published recovery point
    assert result is None
    snap = coordinator.snapshot()
    assert snap["state"] == "ABORTED"
    assert snap["step_state"] != "COMMITTED"
    assert "committed_at" not in snap["milestones"]
    assert snap["latest_checkpoint_id"] is None
    assert snap["epoch"] == before["epoch"]
    assert snap["next_batch_ordinal"] == before["next_batch_ordinal"]

    events = coordinator._events.drain()
    assert all(event.event_type != "checkpoint.saved" for event in events)


def test_a2_worker_failure_during_checkpoint_write_does_not_publish(tmp_path, monkeypatch):
    """A2: worker_failed() during blocking write → checkpoint not published."""
    coordinator, manager = running(tmp_path)
    op, _ = updated(coordinator)
    applied(coordinator, op)
    before = coordinator.snapshot()
    entered, release = Event(), Event()
    original = manager.write

    def delayed(snapshot):
        entered.set()
        assert release.wait(5)
        return original(snapshot)

    monkeypatch.setattr(manager, "write", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(coordinator.checkpoint)
        assert entered.wait(5)
        coordinator.worker_failed(0, 1)
        release.set()
        result = writing.result(timeout=5)
    assert result is None
    snap = coordinator.snapshot()
    assert snap["state"] == "FAILED"
    assert snap["step_state"] != "COMMITTED"
    assert "committed_at" not in snap["milestones"]
    assert snap["latest_checkpoint_id"] is None
    assert snap["epoch"] == before["epoch"]
    assert snap["next_batch_ordinal"] == before["next_batch_ordinal"]

    events = coordinator._events.drain()
    assert all(event.event_type != "checkpoint.saved" for event in events)


def test_a3_normal_checkpoint_still_publishes_and_advances_cursor(tmp_path):
    """A3: normal (no race) checkpoint still publishes and advances cursor."""
    coordinator, manager = running(tmp_path)
    op, _ = updated(coordinator)
    applied(coordinator, op)
    complete = coordinator.checkpoint()
    assert complete is not None
    assert complete.state == "COMPLETE"
    snap = coordinator.snapshot()
    assert snap["state"] == "RUNNING"
    assert snap["step_state"] == "COMMITTED"
    assert snap["latest_checkpoint_id"] == complete.snapshot.checkpoint_id
    assert "committed_at" in snap["milestones"]
    assert manager.verify(complete).model.model_version == 8


def test_a4_previous_valid_checkpoint_survives_aborted_step(tmp_path, monkeypatch):
    """A4: good checkpoint from step N remains valid after step N+1 is aborted."""
    coordinator, manager = running(tmp_path)
    # Step 0: normal path
    op0, _ = updated(coordinator)
    applied(coordinator, op0)
    previous = coordinator.checkpoint()
    assert previous is not None

    # Step 1: abort during write
    op1, _ = updated(coordinator)
    applied(coordinator, op1)
    entered, release = Event(), Event()
    original = manager.write

    def delayed(snapshot):
        entered.set()
        assert release.wait(5)
        return original(snapshot)

    monkeypatch.setattr(manager, "write", delayed)
    with ThreadPoolExecutor(max_workers=2) as pool:
        writing = pool.submit(coordinator.checkpoint)
        assert entered.wait(5)
        pool.submit(coordinator.abort).result(timeout=2)
        release.set()
        result = writing.result(timeout=5)

    assert result is None
    snap = coordinator.snapshot()
    assert snap["state"] == "ABORTED"
    assert snap["latest_checkpoint_id"] == previous.snapshot.checkpoint_id
    # The previous step's checkpoint is still independently verifiable
    assert manager.verify(previous).model.model_version == 8
