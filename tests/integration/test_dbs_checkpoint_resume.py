"""Integration tests for DBS Checkpoint Resume Warm-Up Semantics (T6.1).

Follows canonical requirements (docs/DBS_DESIGN.md §12, docs/DBS_IMPLEMENTATION_PLAN.md.md §16):
1. Checkpoint V1 schema is strictly preserved (no Checkpoint V2, no DBS stats in snapshot).
2. Boundary resume (next_batch_ordinal == 0):
   - Current epoch runs Equal plan.
   - Stats collection is enabled (collect_stats == True).
   - Next epoch transitions to DBS using full epoch stats.
3. Mid-epoch resume (next_batch_ordinal > 0):
   - Remainder of current epoch runs Equal plan.
   - Stats collection is disabled (collect_stats == False).
   - Next full epoch runs Equal plan with stats collection enabled.
   - Subsequent epoch transitions to DBS.
4. BatchScheduler accurately generates remaining Work Units from cursor without duplicates/skips.
"""

import numpy as np

from pbl4.common.work_unit import WorkUnitRef
from pbl4.runtime.batch_scheduler import BatchScheduler, RecoveryCursor
from pbl4.runtime.canonical_model import CanonicalModel, ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointManager
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.coordinator import Coordinator
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.snapshot import CheckpointSnapshot
from pbl4.runtime.synchronization.base import ParameterApplied
from pbl4.runtime.synchronization.context import Member, StrategyContext
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.runtime.workload_scheduler import WorkloadScheduler
from tests.test_checkpoint_mechanics import TestOnlySerializer


def _create_coordinator_with_cursor(
    tmp_path,
    cursor: RecoveryCursor,
    model_version: int = 0,
    total_epochs: int = 4,
    units_per_step: int = 4,
    expected_workers: int = 2,
):
    ctx = StrategyContext(
        job_id="job-resume",
        attempt_id="att-resume",
        contract_hash="hash-contract",
        training_strategy="strict_bsp",
        expected_workers=expected_workers,
        update_policy="plain_sgd",
        dataset_build_id="build-resume",
        dataset_manifest_hash="hash-dataset",
        parameter_manifest_hash="hash-param",
        protocol_version=1,
        total_numel=2,
        membership=tuple(Member(w, w + 10) for w in range(expected_workers)),
    )

    registry = WorkerRegistry("att-resume", expected_workers)
    for w in range(expected_workers):
        registry.register(w + 10, 0, w)

    # 8 total Work Units (4 per shard), K=4 -> 2 steps per epoch
    work_units = []
    for s in range(2):
        for b in range(4):
            work_units.append(WorkUnitRef(shard_id=s, batch_id=b, sample_count=32))

    batch_scheduler = BatchScheduler(
        work_units=work_units,
        training_seed=42,
        epochs=total_epochs,
        work_units_per_step=units_per_step,
        worker_ids=list(range(expected_workers)),
    )
    workload_scheduler = WorkloadScheduler(
        policy="dbs",
        worker_ids=list(range(expected_workers)),
        work_units_per_step=units_per_step,
    )

    initial_params = np.array([1.0, 2.0], dtype=np.float32)
    model = CanonicalModel(initial_params, model_version, "hash-param")
    engine = UpdateEngine(model, "att-resume", "plain_sgd", 0.1)
    events = EventEmitter("att-resume", "job-resume", capacity=100)

    snapshot_template = CheckpointSnapshot(
        checkpoint_id="tmpl",
        checkpoint_schema_version=1,
        job_id="job-resume",
        created_by_attempt_id="att-resume",
        contract_hash="hash-contract",
        checkpoint_policy="after_each_model_update_blocking",
        checkpoint_policy_version=1,
        training_strategy="strict_bsp",
        dataset_build_id="build-resume",
        dataset_manifest_hash="hash-dataset",
        model_id="test-model",
        model_profile="dense_mlp",
        source_operation_id=0,
        source_step_id=None,
        optimizer="plain_sgd",
        created_at="2026-09-24T00:00:00Z",
        model=ModelSnapshot(model_version, "hash-param", initial_params.tobytes()),
        recovery_cursor=cursor,
    )

    manager = CheckpointManager(tmp_path, TestOnlySerializer())

    coordinator = Coordinator(
        ctx,
        registry,
        create_policy(ctx),
        model,
        engine,
        batch_scheduler,
        CheckpointPolicy("after_each_model_update_blocking"),
        manager,
        snapshot_template,
        events,
        cursor=cursor,
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

    return coordinator, workload_scheduler, batch_scheduler, manager, events


def test_dbs_checkpoint_boundary_resume(tmp_path) -> None:
    """Test boundary resume: RecoveryCursor(epoch=1, next_batch_ordinal=0).

    Expected:
    - Resumed epoch 1 uses Equal plan (2 units each).
    - Stats collection is enabled during epoch 1.
    - After epoch 1 completes (2 steps), epoch 2 transitions to DBS allocating 3 units
      to faster worker and 1 to slower worker.
    - Checkpoint V1 schema is strictly verified.
    """
    resume_cursor = RecoveryCursor(epoch=1, next_batch_ordinal=0)
    coordinator, workload_scheduler, _batch_scheduler, manager, events = (
        _create_coordinator_with_cursor(tmp_path, resume_cursor, model_version=2)
    )

    # Verify initial warm-up state
    assert workload_scheduler.current_epoch == 1
    assert workload_scheduler.collect_stats is True
    plan1 = workload_scheduler.plan_for_epoch(1)
    assert plan1.policy == "equal"
    assert plan1.units_per_worker == {0: 2, 1: 2}

    # === Epoch 1, Step 0 ===
    op1_0 = coordinator.open_step()
    assert op1_0.epoch == 1
    assert op1_0.batch_ordinal == 0
    # Equal allocation: each worker has 2 work units
    assert len(op1_0.assignments[0].work_units) == 2
    assert len(op1_0.assignments[1].work_units) == 2

    grad = np.array([0.1, 0.2], dtype=np.float32)
    # Worker 0: 64 samples in 200 ms (throughput = 0.32)
    # Worker 1: 64 samples in 100 ms (throughput = 0.64 -> 2x faster)
    c1_0_0 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=10,
        worker_id=0,
        operation_id=op1_0.operation_id,
        step_id=op1_0.step_id,
        model_version=2,
        shard_id=op1_0.assignments[0].shard_id,
        batch_id=op1_0.assignments[0].batch_id,
        batch_ordinal=0,
        sample_count=op1_0.assignments[0].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=200.0,
    )
    c1_0_1 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=11,
        worker_id=1,
        operation_id=op1_0.operation_id,
        step_id=op1_0.step_id,
        model_version=2,
        shard_id=op1_0.assignments[1].shard_id,
        batch_id=op1_0.assignments[1].batch_id,
        batch_ordinal=0,
        sample_count=op1_0.assignments[1].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )
    coordinator.admit(c1_0_0)
    coordinator.admit(c1_0_1)
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 10, 0, op1_0.operation_id, op1_0.step_id, 3)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 11, 1, op1_0.operation_id, op1_0.step_id, 3)
    )
    cp1_0 = coordinator.checkpoint()
    assert cp1_0 is not None
    assert cp1_0.state == "COMPLETE"
    # Verify checkpoint persistence preserves V1 schema
    verified1_0 = manager.verify(cp1_0)
    assert verified1_0.checkpoint_schema_version == 1
    assert verified1_0.recovery_cursor == RecoveryCursor(epoch=1, next_batch_ordinal=1)

    # === Epoch 1, Step 1 ===
    op1_1 = coordinator.open_step()
    assert op1_1.epoch == 1
    assert op1_1.batch_ordinal == 1

    c1_1_0 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=10,
        worker_id=0,
        operation_id=op1_1.operation_id,
        step_id=op1_1.step_id,
        model_version=3,
        shard_id=op1_1.assignments[0].shard_id,
        batch_id=op1_1.assignments[0].batch_id,
        batch_ordinal=1,
        sample_count=op1_1.assignments[0].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=200.0,
    )
    c1_1_1 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=11,
        worker_id=1,
        operation_id=op1_1.operation_id,
        step_id=op1_1.step_id,
        model_version=3,
        shard_id=op1_1.assignments[1].shard_id,
        batch_id=op1_1.assignments[1].batch_id,
        batch_ordinal=1,
        sample_count=op1_1.assignments[1].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )
    coordinator.admit(c1_1_0)
    coordinator.admit(c1_1_1)
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 10, 0, op1_1.operation_id, op1_1.step_id, 4)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 11, 1, op1_1.operation_id, op1_1.step_id, 4)
    )
    cp1_1 = coordinator.checkpoint()
    assert cp1_1 is not None
    assert cp1_1.state == "COMPLETE"
    assert cp1_1.snapshot.recovery_cursor == RecoveryCursor(epoch=2, next_batch_ordinal=0)

    # Epoch 1 completed! Telemetry event emitted for epoch 2
    drained = events.drain()
    plan_events = [e for e in drained if e.event_type == "workload.plan_changed"]
    assert len(plan_events) == 1
    assert plan_events[0].details["epoch"] == 2
    assert plan_events[0].details["policy"] == "dbs"

    # === Epoch 2, Step 0 ===
    op2_0 = coordinator.open_step()
    assert op2_0.epoch == 2
    assert op2_0.batch_ordinal == 0
    # DBS allocation: Worker 0 has 1 unit, Worker 1 has 3 units
    assert len(op2_0.assignments[0].work_units) == 1
    assert len(op2_0.assignments[1].work_units) == 3


def test_dbs_checkpoint_mid_epoch_resume(tmp_path) -> None:
    """Test mid-epoch resume: RecoveryCursor(epoch=1, next_batch_ordinal=1).

    Expected:
    - Remainder of epoch 1 (step 1) runs Equal plan.
    - Stats collection is disabled (collect_stats == False).
    - When epoch 1 completes, epoch 2 runs with Equal plan and stats collection ENABLED.
    - After full epoch 2 completes, epoch 3 transitions to DBS.
    """
    # 2 steps per epoch (ordinal 0 and 1). Resuming at ordinal 1 is mid-epoch.
    resume_cursor = RecoveryCursor(epoch=1, next_batch_ordinal=1)
    coordinator, workload_scheduler, _batch_scheduler, _manager, _events = (
        _create_coordinator_with_cursor(tmp_path, resume_cursor, model_version=3)
    )

    assert workload_scheduler.current_epoch == 1
    assert workload_scheduler.collect_stats is False
    plan1 = workload_scheduler.plan_for_epoch(1)
    assert plan1.policy == "equal"

    # === Remainder of Epoch 1: Step 1 ===
    op1_1 = coordinator.open_step()
    assert op1_1.epoch == 1
    assert op1_1.batch_ordinal == 1
    # Equal allocation
    assert len(op1_1.assignments[0].work_units) == 2
    assert len(op1_1.assignments[1].work_units) == 2

    grad = np.array([0.1, 0.2], dtype=np.float32)
    # Recorded stats during this partial epoch must be ignored
    c1_1_0 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=10,
        worker_id=0,
        operation_id=op1_1.operation_id,
        step_id=op1_1.step_id,
        model_version=3,
        shard_id=op1_1.assignments[0].shard_id,
        batch_id=op1_1.assignments[0].batch_id,
        batch_ordinal=1,
        sample_count=op1_1.assignments[0].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=500.0,  # Deliberately skewed numbers
    )
    c1_1_1 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=11,
        worker_id=1,
        operation_id=op1_1.operation_id,
        step_id=op1_1.step_id,
        model_version=3,
        shard_id=op1_1.assignments[1].shard_id,
        batch_id=op1_1.assignments[1].batch_id,
        batch_ordinal=1,
        sample_count=op1_1.assignments[1].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=10.0,
    )
    coordinator.admit(c1_1_0)
    coordinator.admit(c1_1_1)
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 10, 0, op1_1.operation_id, op1_1.step_id, 4)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 11, 1, op1_1.operation_id, op1_1.step_id, 4)
    )
    cp1_1 = coordinator.checkpoint()
    assert cp1_1 is not None
    assert cp1_1.snapshot.recovery_cursor == RecoveryCursor(epoch=2, next_batch_ordinal=0)

    # Next epoch 2 must STILL be Equal, but with stats collection re-enabled!
    assert workload_scheduler.current_epoch == 2
    assert workload_scheduler.collect_stats is True
    plan2 = workload_scheduler.plan_for_epoch(2)
    assert plan2.policy == "equal"
    assert plan2.units_per_worker == {0: 2, 1: 2}

    # === Epoch 2, Step 0 ===
    op2_0 = coordinator.open_step()
    assert op2_0.epoch == 2
    assert op2_0.batch_ordinal == 0
    assert len(op2_0.assignments[0].work_units) == 2
    assert len(op2_0.assignments[1].work_units) == 2

    # Worker 0: 200 ms, Worker 1: 100 ms (2x faster)
    c2_0_0 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=10,
        worker_id=0,
        operation_id=op2_0.operation_id,
        step_id=op2_0.step_id,
        model_version=4,
        shard_id=op2_0.assignments[0].shard_id,
        batch_id=op2_0.assignments[0].batch_id,
        batch_ordinal=0,
        sample_count=op2_0.assignments[0].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=200.0,
    )
    c2_0_1 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=11,
        worker_id=1,
        operation_id=op2_0.operation_id,
        step_id=op2_0.step_id,
        model_version=4,
        shard_id=op2_0.assignments[1].shard_id,
        batch_id=op2_0.assignments[1].batch_id,
        batch_ordinal=0,
        sample_count=op2_0.assignments[1].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )
    coordinator.admit(c2_0_0)
    coordinator.admit(c2_0_1)
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 10, 0, op2_0.operation_id, op2_0.step_id, 5)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 11, 1, op2_0.operation_id, op2_0.step_id, 5)
    )
    coordinator.checkpoint()

    # === Epoch 2, Step 1 ===
    op2_1 = coordinator.open_step()
    assert op2_1.epoch == 2
    assert op2_1.batch_ordinal == 1

    c2_1_0 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=10,
        worker_id=0,
        operation_id=op2_1.operation_id,
        step_id=op2_1.step_id,
        model_version=5,
        shard_id=op2_1.assignments[0].shard_id,
        batch_id=op2_1.assignments[0].batch_id,
        batch_ordinal=1,
        sample_count=op2_1.assignments[0].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=200.0,
    )
    c2_1_1 = Contribution.from_gradient(
        grad,
        attempt_id="att-resume",
        session_id=11,
        worker_id=1,
        operation_id=op2_1.operation_id,
        step_id=op2_1.step_id,
        model_version=5,
        shard_id=op2_1.assignments[1].shard_id,
        batch_id=op2_1.assignments[1].batch_id,
        batch_ordinal=1,
        sample_count=op2_1.assignments[1].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )
    coordinator.admit(c2_1_0)
    coordinator.admit(c2_1_1)
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 10, 0, op2_1.operation_id, op2_1.step_id, 6)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-resume", 11, 1, op2_1.operation_id, op2_1.step_id, 6)
    )
    cp2_1 = coordinator.checkpoint()
    assert cp2_1 is not None
    assert cp2_1.snapshot.recovery_cursor == RecoveryCursor(epoch=3, next_batch_ordinal=0)

    # Epoch 2 completed! Epoch 3 transitions to DBS!
    assert workload_scheduler.current_epoch == 3
    plan3 = workload_scheduler.plan_for_epoch(3)
    assert plan3.policy == "dbs"
    assert plan3.units_per_worker == {0: 1, 1: 3}

    op3_0 = coordinator.open_step()
    assert op3_0.epoch == 3
    assert len(op3_0.assignments[0].work_units) == 1
    assert len(op3_0.assignments[1].work_units) == 3
