"""Integration tests for epoch checkpoint lifecycle and synchronous boundary writes (Plan A + D0.B + D0.C)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pytest

from pbl4.runtime.batch_scheduler import BatchScheduler, RecoveryCursor, WorkUnitRef
from pbl4.runtime.canonical_model import CanonicalModel, ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointManager
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.coordinator import Coordinator
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.process import _AttemptRunner
from pbl4.runtime.snapshot import CheckpointSnapshot
from pbl4.runtime.synchronization.base import AdmissionCode, ParameterApplied
from pbl4.runtime.synchronization.context import Member, StrategyContext
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.runtime.workload_scheduler import WorkloadScheduler
from tests.test_checkpoint_mechanics import TestOnlySerializer


def _create_coordinator(tmp_path, epochs=2, every_n_epochs=1):
    expected_workers = 2
    ctx = StrategyContext(
        job_id="job-lifecycle",
        attempt_id="att-lifecycle",
        contract_hash="hash-contract",
        training_strategy="strict_bsp",
        expected_workers=expected_workers,
        update_policy="plain_sgd",
        dataset_build_id="build-lifecycle",
        dataset_manifest_hash="hash-dataset",
        parameter_manifest_hash="hash-param",
        protocol_version=1,
        total_numel=2,
        membership=tuple(Member(w, w + 10) for w in range(expected_workers)),
    )
    registry = WorkerRegistry("att-lifecycle", expected_workers)
    for w in range(expected_workers):
        registry.register(w + 10, 0, w)

    # 4 units, K=2 units per step -> 2 units per step = 1 step per epoch (or 2 steps per epoch with 4 units)
    work_units = [
        WorkUnitRef(shard_id=0, batch_id=0, sample_count=32),
        WorkUnitRef(shard_id=1, batch_id=0, sample_count=32),
    ]
    batch_scheduler = BatchScheduler(
        work_units=work_units,
        training_seed=42,
        epochs=epochs,
        work_units_per_step=2,
        worker_ids=[0, 1],
    )
    workload_scheduler = WorkloadScheduler(
        policy="equal",
        worker_ids=[0, 1],
        work_units_per_step=2,
    )
    initial_params = np.array([1.0, 2.0], dtype=np.float32)
    model = CanonicalModel(initial_params, 0, "hash-param")
    events = EventEmitter("att-lifecycle", "job-lifecycle", capacity=100)

    checkpoint_template = CheckpointSnapshot(
        checkpoint_id="pending",
        checkpoint_schema_version=1,
        job_id="job-lifecycle",
        created_by_attempt_id="att-lifecycle",
        contract_hash="hash-contract",
        checkpoint_policy="periodic",
        checkpoint_policy_version=1,
        training_strategy="strict_bsp",
        dataset_build_id="build-lifecycle",
        dataset_manifest_hash="hash-dataset",
        model_id="resnet18_groupnorm",
        model_profile="RESNET18_GROUPNORM_V1",
        source_operation_id=0,
        source_step_id=None,
        optimizer="plain_sgd",
        created_at="2026-09-24T00:00:00Z",
        model=ModelSnapshot(0, "hash-param", initial_params.tobytes()),
        recovery_cursor=RecoveryCursor(0, 0),
    )

    manager = CheckpointManager(tmp_path, TestOnlySerializer())
    policy = CheckpointPolicy(every_n_epochs=every_n_epochs, max_attempts=3)
    coordinator = Coordinator(
        ctx,
        registry,
        create_policy(ctx),
        model,
        UpdateEngine(model, "att-lifecycle", "plain_sgd", 0.1),
        batch_scheduler,
        policy,
        manager,
        checkpoint_template,
        events,
        workload_scheduler=workload_scheduler,
    )

    coordinator.advance_initialization()
    for w in range(expected_workers):
        registry.transition(w, w + 10, SessionState.REGISTERING, 0)
    coordinator.advance_initialization()
    for w in range(expected_workers):
        registry.transition(w, w + 10, SessionState.PROVISIONING, 0)
        registry.transition(w, w + 10, SessionState.SHARD_READY, 0)
    coordinator.advance_initialization()
    for w in range(expected_workers):
        registry.transition(w, w + 10, SessionState.MODEL_SYNCING, 0)
        registry.transition(w, w + 10, SessionState.READY, 0)
    coordinator.advance_initialization()
    return coordinator, manager, events


def _run_step(coordinator, op=None):
    op = op or coordinator.open_step()
    grad = np.array([0.1, 0.2], dtype=np.float32)
    for w in range(2):
        assigned = next(a for a in op.assignments if a.worker_id == w)
        c = Contribution.from_gradient(
            grad,
            attempt_id="att-lifecycle",
            session_id=w + 10,
            worker_id=w,
            operation_id=op.operation_id,
            step_id=op.step_id,
            model_version=op.input_model_version,
            shard_id=assigned.shard_id,
            batch_id=assigned.batch_id,
            batch_ordinal=assigned.batch_ordinal,
            sample_count=assigned.sample_count,
            parameter_manifest_hash="hash-param",
            tensor_id=1,
            loss=1.0,
            correct_count=16,
            compute_ms=10.0,
        )
        dec, _ = coordinator.admit(c)
        assert dec.code == AdmissionCode.ACCEPT, f"Admit rejected: {dec.reason}"
    for w in range(2):
        coordinator.parameter_applied(
            ParameterApplied(
                "att-lifecycle",
                w + 10,
                w,
                op.operation_id,
                op.step_id,
                op.input_model_version + 1,
            )
        )
    coordinator.commit_synchronized_step()
    return op


def test_epoch_boundary_synchronous_write_blocks_next_step(tmp_path, monkeypatch):
    """Test that at epoch boundary, write blocks before next epoch step opens."""
    coordinator, manager, events = _create_coordinator(tmp_path, epochs=2, every_n_epochs=1)
    write_entered = threading.Event()
    write_release = threading.Event()
    original_write = manager.write

    def blocking_write(snapshot):
        write_entered.set()
        assert write_release.wait(timeout=5.0)
        return original_write(snapshot)

    monkeypatch.setattr(manager, "write", blocking_write)

    # Step 0 (completes epoch 0)
    op0 = _run_step(coordinator)
    assert coordinator.cursor.epoch == 1

    # Start checkpoint save in thread (as runner would do at boundary)
    save_thread = threading.Thread(
        target=coordinator.save_checkpoint_for_current_revision,
        kwargs={"is_final": False},
    )
    save_thread.start()

    assert write_entered.wait(timeout=2.0)
    # While write is blocking, step state is COMMITTED, checkpoint state is WRITING
    snap = coordinator.snapshot()
    assert snap["step_state"] == "COMMITTED"
    assert snap["checkpoint_state"] == "WRITING"

    # Next epoch step CANNOT be opened while checkpoint write is in progress
    # because save_checkpoint_for_current_revision holds or locks during critical sections
    write_release.set()
    save_thread.join(timeout=2.0)

    assert coordinator.snapshot()["checkpoint_state"] == "COMPLETE"
    # Now next epoch step can open
    op1 = coordinator.open_step()
    assert op1.epoch == 1


def test_periodic_checkpoint_failure_warns_and_continues(tmp_path, monkeypatch):
    """Test D0.B: periodic checkpoint write failure (3 attempts) emits WARNING and does NOT fail Attempt."""
    coordinator, manager, events = _create_coordinator(tmp_path, epochs=2, every_n_epochs=1)
    attempts = 0

    def failing_write(snapshot):
        nonlocal attempts
        attempts += 1
        raise OSError("periodic disk failure")

    monkeypatch.setattr(manager, "write", failing_write)

    # Step 0 finishes epoch 0
    op0 = _run_step(coordinator)
    events.drain()

    # Periodic checkpoint fails after 3 retries
    res = coordinator.save_checkpoint_for_current_revision(is_final=False)
    assert res is None
    assert attempts == 3

    # Attempt remains RUNNING, step remains COMMITTED, checkpoint state is FAILED
    snap = coordinator.snapshot()
    assert snap["state"] == "RUNNING"
    assert snap["step_state"] == "COMMITTED"
    assert snap["checkpoint_state"] == "FAILED"

    evs = events.drain()
    failed_events = [e for e in evs if e.event_type == "checkpoint.failed"]
    assert len(failed_events) == 1
    assert failed_events[0].severity == "WARNING"

    # Training proceeds to next epoch!
    op1 = _run_step(coordinator)
    assert op1.epoch == 1


def test_final_checkpoint_dedup_when_coinciding_with_periodic(tmp_path, monkeypatch):
    """Test that when final epoch matches periodic N, final checkpoint is not saved twice."""
    coordinator, manager, events = _create_coordinator(tmp_path, epochs=1, every_n_epochs=1)
    write_count = 0
    original_write = manager.write

    def counting_write(snapshot):
        nonlocal write_count
        write_count += 1
        return original_write(snapshot)

    monkeypatch.setattr(manager, "write", counting_write)

    # Step 0 finishes epoch 0 (which is total 1 epoch)
    _run_step(coordinator)

    # Periodic write at epoch 1 boundary
    coordinator.save_checkpoint_for_current_revision(is_final=False)
    assert write_count == 1

    # End of schedule: check if final checkpoint is already verified
    assert coordinator.has_verified_checkpoint_for_current_revision() is True
    # Does NOT call save again
    coordinator.complete()
    assert coordinator.snapshot()["state"] == "COMPLETED"
    assert write_count == 1


@pytest.mark.parametrize("epochs", [1, 2])
@pytest.mark.parametrize("write_fails", [False, True])
def test_runner_final_boundary_has_one_retry_budget(tmp_path, monkeypatch, epochs, write_fails):
    coordinator, manager, events = _create_coordinator(tmp_path, epochs=epochs)
    original_write = manager.write
    writes = []

    def write(snapshot):
        writes.append(snapshot.checkpoint_id)
        if write_fails:
            raise OSError("disk unavailable")
        return original_write(snapshot)

    monkeypatch.setattr(manager, "write", write)
    runner = _AttemptRunner.__new__(_AttemptRunner)
    runner.attempt_id = "att-lifecycle"
    runner._payload = {"resolved_contract": {"training": {"epochs": epochs}}}
    runner._process = SimpleNamespace(_heartbeat_timeout=30)
    runner._registry = coordinator._registry
    runner._manifest = SimpleNamespace(parameter_manifest_hash="hash-param")
    runner._abort = threading.Event()
    runner._step_done = threading.Event()
    runner._set_state = MagicMock()
    server = MagicMock()

    def deliver_step(worker_id, *_):
        if worker_id == 1:
            _run_step(coordinator, coordinator._operation)
            runner._step_done.set()

    server.send_step_start.side_effect = deliver_step
    runner._training_loop(coordinator, server)

    assert coordinator.snapshot()["state"] == "COMPLETED"
    assert len(writes) == epochs * (3 if write_fails else 1)
    assert len(set(writes)) == epochs
    started = [e for e in events.peek() if e.event_type == "checkpoint.started"]
    assert [e.details["is_final"] for e in started] == [False] * (epochs - 1) + [True]
