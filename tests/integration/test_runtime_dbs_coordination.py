"""Integration test: Coordinator + WorkloadScheduler + BatchScheduler + StrictBSP.

Verifies end-to-end DBS coordination in Runtime:
1. Epoch 0 opens steps with Equal plan (K units split evenly).
2. Committed contributions record timing stats on checkpoint commit.
3. Epoch boundary transition triggers DBS plan evaluation and emits workload.plan_changed event.
4. Epoch 1 opens steps with the computed DBS plan allocating more Work Units to faster workers.
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


def test_runtime_dbs_coordination_multi_epoch(tmp_path) -> None:
    expected_workers = 2
    ctx = StrategyContext(
        job_id="job-dbs",
        attempt_id="att-dbs",
        contract_hash="hash-contract",
        training_strategy="strict_bsp",
        expected_workers=expected_workers,
        update_policy="plain_sgd",
        dataset_build_id="build-dbs",
        dataset_manifest_hash="hash-dataset",
        parameter_manifest_hash="hash-param",
        protocol_version=1,
        total_numel=2,
        membership=tuple(Member(w, w + 10) for w in range(expected_workers)),
    )

    registry = WorkerRegistry("att-dbs", expected_workers)
    for w in range(expected_workers):
        registry.register(w + 10, 0, w)

    # 8 total Work Units (4 per shard), K=4 units per step -> 2 steps per epoch
    work_units = []
    for s in range(2):
        for b in range(4):
            work_units.append(WorkUnitRef(shard_id=s, batch_id=b, sample_count=32))

    batch_scheduler = BatchScheduler(
        work_units=work_units,
        training_seed=42,
        epochs=2,
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
    events = EventEmitter("att-dbs", "job-dbs", capacity=100)

    checkpoint_template = CheckpointSnapshot(
        checkpoint_id="pending",
        checkpoint_schema_version=1,
        job_id="job-dbs",
        created_by_attempt_id="att-dbs",
        contract_hash="hash-contract",
        checkpoint_policy="after_each_model_update_blocking",
        checkpoint_policy_version=1,
        training_strategy="strict_bsp",
        dataset_build_id="build-dbs",
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

    coordinator = Coordinator(
        ctx,
        registry,
        create_policy(ctx),
        model,
        UpdateEngine(model, "att-dbs", "plain_sgd", 0.1),
        batch_scheduler,
        CheckpointPolicy(),
        CheckpointManager(tmp_path, TestOnlySerializer()),
        checkpoint_template,
        events,
        workload_scheduler=workload_scheduler,
    )

    # Advance lifecycle to RUNNING
    coordinator.advance_initialization()  # WAITING_WORKERS
    for w in range(expected_workers):
        registry.transition(w, w + 10, SessionState.REGISTERING, 0)
    coordinator.advance_initialization()  # PROVISIONING
    for w in range(expected_workers):
        registry.transition(w, w + 10, SessionState.PROVISIONING, 0)
        registry.transition(w, w + 10, SessionState.SHARD_READY, 0)
    coordinator.advance_initialization()  # INITIALIZING
    for w in range(expected_workers):
        registry.transition(w, w + 10, SessionState.MODEL_SYNCING, 0)
        registry.transition(w, w + 10, SessionState.READY, 0)
    assert coordinator.advance_initialization() == "RUNNING"

    grad = np.array([0.1, 0.2], dtype=np.float32)

    # === Epoch 0, Step 0 ===
    op0 = coordinator.open_step()
    assert op0.epoch == 0
    assert op0.batch_ordinal == 0
    # Equal plan in epoch 0: 2 units each (64 samples each)
    assign_map0 = {a.worker_id: a for a in op0.assignments}
    assert len(assign_map0[0].work_units) == 2
    assert len(assign_map0[1].work_units) == 2
    assert assign_map0[0].sample_count == 64
    assert assign_map0[1].sample_count == 64

    # Worker 0 slower (compute_ms = 200.0), Worker 1 faster (compute_ms = 100.0)
    c0_0 = Contribution.from_gradient(
        grad,
        attempt_id="att-dbs",
        session_id=10,
        worker_id=0,
        operation_id=op0.operation_id,
        step_id=op0.step_id,
        model_version=0,
        shard_id=assign_map0[0].shard_id,
        batch_id=assign_map0[0].batch_id,
        batch_ordinal=0,
        sample_count=64,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=200.0,
    )
    c0_1 = Contribution.from_gradient(
        grad,
        attempt_id="att-dbs",
        session_id=11,
        worker_id=1,
        operation_id=op0.operation_id,
        step_id=op0.step_id,
        model_version=0,
        shard_id=assign_map0[1].shard_id,
        batch_id=assign_map0[1].batch_id,
        batch_ordinal=0,
        sample_count=64,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )
    coordinator.admit(c0_0)
    _dec0, published0 = coordinator.admit(c0_1)
    assert published0 is not None
    assert published0.model_version == 1

    coordinator.parameter_applied(
        ParameterApplied("att-dbs", 10, 0, op0.operation_id, op0.step_id, 1)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-dbs", 11, 1, op0.operation_id, op0.step_id, 1)
    )
    cp0 = coordinator.checkpoint()
    assert cp0 is not None
    assert cp0.state == "COMPLETE"

    # === Epoch 0, Step 1 ===
    op1 = coordinator.open_step()
    assert op1.epoch == 0
    assert op1.batch_ordinal == 1
    assign_map1 = {a.worker_id: a for a in op1.assignments}
    assert len(assign_map1[0].work_units) == 2
    assert len(assign_map1[1].work_units) == 2

    c1_0 = Contribution.from_gradient(
        grad,
        attempt_id="att-dbs",
        session_id=10,
        worker_id=0,
        operation_id=op1.operation_id,
        step_id=op1.step_id,
        model_version=1,
        shard_id=assign_map1[0].shard_id,
        batch_id=assign_map1[0].batch_id,
        batch_ordinal=1,
        sample_count=64,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=200.0,
    )
    c1_1 = Contribution.from_gradient(
        grad,
        attempt_id="att-dbs",
        session_id=11,
        worker_id=1,
        operation_id=op1.operation_id,
        step_id=op1.step_id,
        model_version=1,
        shard_id=assign_map1[1].shard_id,
        batch_id=assign_map1[1].batch_id,
        batch_ordinal=1,
        sample_count=64,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )
    coordinator.admit(c1_0)
    _dec1, published1 = coordinator.admit(c1_1)
    assert published1 is not None
    assert published1.model_version == 2

    coordinator.parameter_applied(
        ParameterApplied("att-dbs", 10, 0, op1.operation_id, op1.step_id, 2)
    )
    coordinator.parameter_applied(
        ParameterApplied("att-dbs", 11, 1, op1.operation_id, op1.step_id, 2)
    )
    cp1 = coordinator.checkpoint()
    assert cp1 is not None

    # Epoch 0 completed! Check event emitted
    event_list = events.drain()
    plan_events = [e for e in event_list if e.event_type == "workload.plan_changed"]
    assert len(plan_events) == 1
    plan_data = plan_events[0].details
    assert plan_data["epoch"] == 1
    assert plan_data["policy"] == "dbs"
    # Worker 1 is 2x faster -> units {0: 1, 1: 3}
    assert plan_data["units_per_worker"] in ({0: 1, 1: 3}, {"0": 1, "1": 3})

    # === Epoch 1, Step 0 ===
    op2 = coordinator.open_step()
    assert op2.epoch == 1
    assert op2.batch_ordinal == 0
    assign_map2 = {a.worker_id: a for a in op2.assignments}

    # Worker 0 receives 1 WorkUnit, Worker 1 receives 3 WorkUnits!
    assert len(assign_map2[0].work_units) == 1
    assert len(assign_map2[1].work_units) == 3
    assert assign_map2[0].sample_count == 32
    assert assign_map2[1].sample_count == 96
    assert sum(len(a.work_units) for a in op2.assignments) == 4
