"""Unit tests for DBS observability telemetry (T6.2).

Verifies:
1. workload.plan_changed event is emitted on WorkloadPlan transition at epoch boundary.
2. Event details match canonical contract (epoch, policy, units_per_worker, target_ratios).
3. Telemetry emission failure does not break step progression or training loop.
"""

from unittest.mock import MagicMock

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


def _setup_coordinator(tmp_path, event_capacity: int = 100):
    expected_workers = 2
    ctx = StrategyContext(
        job_id="job-telem",
        attempt_id="att-telem",
        contract_hash="hash-contract",
        training_strategy="strict_bsp",
        expected_workers=expected_workers,
        update_policy="plain_sgd",
        dataset_build_id="build-telem",
        dataset_manifest_hash="hash-dataset",
        parameter_manifest_hash="hash-param",
        protocol_version=1,
        total_numel=2,
        membership=tuple(Member(w, w + 10) for w in range(expected_workers)),
    )

    registry = WorkerRegistry("att-telem", expected_workers)
    for w in range(expected_workers):
        registry.register(w + 10, 0, w)

    # 4 Work Units total, K=4 -> exactly 1 step per epoch
    work_units = [
        WorkUnitRef(shard_id=0, batch_id=0, sample_count=32),
        WorkUnitRef(shard_id=0, batch_id=1, sample_count=32),
        WorkUnitRef(shard_id=1, batch_id=0, sample_count=32),
        WorkUnitRef(shard_id=1, batch_id=1, sample_count=32),
    ]

    batch_scheduler = BatchScheduler(
        work_units=work_units,
        training_seed=42,
        epochs=3,
        work_units_per_step=4,
        worker_ids=[0, 1],
    )
    workload_scheduler = WorkloadScheduler(
        policy="dbs",
        worker_ids=[0, 1],
        work_units_per_step=4,
    )

    initial_params = np.array([1.0, 2.0], dtype=np.float32)
    model = CanonicalModel(initial_params, 0, "hash-param")
    engine = UpdateEngine(model, "att-telem", "plain_sgd", 0.1)
    events = EventEmitter("att-telem", "job-telem", capacity=event_capacity)

    snapshot_template = CheckpointSnapshot(
        checkpoint_id="tmpl",
        checkpoint_schema_version=1,
        job_id="job-telem",
        created_by_attempt_id="att-telem",
        contract_hash="hash-contract",
        checkpoint_policy="after_each_model_update_blocking",
        checkpoint_policy_version=1,
        training_strategy="strict_bsp",
        dataset_build_id="build-telem",
        dataset_manifest_hash="hash-dataset",
        model_id="test-model",
        model_profile="dense_mlp",
        source_operation_id=0,
        source_step_id=None,
        optimizer="plain_sgd",
        created_at="2026-09-24T00:00:00Z",
        model=ModelSnapshot(0, "hash-param", initial_params.tobytes()),
        recovery_cursor=RecoveryCursor(0, 0),
    )

    coordinator = Coordinator(
        ctx,
        registry,
        create_policy(ctx),
        model,
        engine,
        batch_scheduler,
        CheckpointPolicy("after_each_model_update_blocking"),
        CheckpointManager(tmp_path, TestOnlySerializer()),
        snapshot_template,
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

    return coordinator, events


def test_workload_plan_changed_event_emitted(tmp_path) -> None:
    coordinator, events = _setup_coordinator(tmp_path)

    # Epoch 0, Step 0
    op = coordinator.open_step()
    grad = np.array([0.1, 0.2], dtype=np.float32)

    # Worker 0: 64 samples in 200 ms (throughput 0.32)
    # Worker 1: 64 samples in 100 ms (throughput 0.64 -> 2x faster)
    c0 = Contribution.from_gradient(
        grad,
        attempt_id="att-telem",
        session_id=10,
        worker_id=0,
        operation_id=op.operation_id,
        step_id=op.step_id,
        model_version=0,
        shard_id=op.assignments[0].shard_id,
        batch_id=op.assignments[0].batch_id,
        batch_ordinal=op.assignments[0].batch_ordinal,
        sample_count=op.assignments[0].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=200.0,
    )
    c1 = Contribution.from_gradient(
        grad,
        attempt_id="att-telem",
        session_id=11,
        worker_id=1,
        operation_id=op.operation_id,
        step_id=op.step_id,
        model_version=0,
        shard_id=op.assignments[1].shard_id,
        batch_id=op.assignments[1].batch_id,
        batch_ordinal=op.assignments[1].batch_ordinal,
        sample_count=op.assignments[1].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )

    coordinator.admit(c0)
    coordinator.admit(c1)
    coordinator.parameter_applied(
        ParameterApplied("att-telem", 10, 0, op.operation_id, op.step_id, 1)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-telem", 11, 1, op.operation_id, op.step_id, 1)
    )

    cp = coordinator.checkpoint()
    assert cp is not None
    assert cp.state == "COMPLETE"

    # Verify workload.plan_changed event was emitted
    drained = events.drain()
    plan_events = [e for e in drained if e.event_type == "workload.plan_changed"]
    assert len(plan_events) == 1

    details = plan_events[0].details
    assert details["epoch"] == 1
    assert details["policy"] == "dbs"
    # Key serialization in event is stringified rank
    assert details["units_per_worker"] in ({"0": 1, "1": 3}, {0: 1, 1: 3})
    assert "target_ratios" in details


def test_telemetry_emission_failure_does_not_break_training(tmp_path) -> None:
    coordinator, events = _setup_coordinator(tmp_path)

    # Monkeypatch emit to simulate an event emission failure specifically on workload.plan_changed
    original_emit = events.emit

    def failing_emit(event_type, details, occurred_at, component, severity="INFO"):
        if event_type == "workload.plan_changed":
            raise RuntimeError("Telemetry bus failure simulation")
        return original_emit(event_type, details, occurred_at, component, severity)

    events.emit = MagicMock(side_effect=failing_emit)

    op = coordinator.open_step()
    grad = np.array([0.1, 0.2], dtype=np.float32)

    c0 = Contribution.from_gradient(
        grad,
        attempt_id="att-telem",
        session_id=10,
        worker_id=0,
        operation_id=op.operation_id,
        step_id=op.step_id,
        model_version=0,
        shard_id=op.assignments[0].shard_id,
        batch_id=op.assignments[0].batch_id,
        batch_ordinal=op.assignments[0].batch_ordinal,
        sample_count=op.assignments[0].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=200.0,
    )
    c1 = Contribution.from_gradient(
        grad,
        attempt_id="att-telem",
        session_id=11,
        worker_id=1,
        operation_id=op.operation_id,
        step_id=op.step_id,
        model_version=0,
        shard_id=op.assignments[1].shard_id,
        batch_id=op.assignments[1].batch_id,
        batch_ordinal=op.assignments[1].batch_ordinal,
        sample_count=op.assignments[1].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )

    coordinator.admit(c0)
    coordinator.admit(c1)
    coordinator.parameter_applied(
        ParameterApplied("att-telem", 10, 0, op.operation_id, op.step_id, 1)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-telem", 11, 1, op.operation_id, op.step_id, 1)
    )

    # Checkpoint must succeed despite telemetry failure
    cp = coordinator.checkpoint()
    assert cp is not None
    assert cp.state == "COMPLETE"

    snap = coordinator.snapshot()
    assert snap["step_state"] == "COMMITTED"
    assert snap["epoch"] == 1
    assert snap["next_batch_ordinal"] == 0
