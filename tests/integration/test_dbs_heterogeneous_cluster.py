"""End-to-end integration test for DBS heterogeneous speed cluster (T7.1).

Follows canonical rules (docs/DBS_DESIGN.md §2, §7, docs/DBS_IMPLEMENTATION_PLAN.md.md §18):
1. 3-Worker cluster with synthetic compute delays / speed differences (e.g. 40ms vs 20ms vs 10ms).
2. Epoch 0 runs Equal plan (K=7 units split across 3 workers).
3. N/N StrictBSP barrier holds on all steps.
4. Epoch boundary transition shifts units proportionally toward faster workers:
   (Worker 2: 4 units, Worker 1: 2 units, Worker 0: 1 unit).
5. Global model parameters update successfully using sample-weighted gradient aggregation.
6. Total K units per step remains invariant (K=7).
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


def test_dbs_heterogeneous_cluster_3_workers(tmp_path) -> None:
    expected_workers = 3
    worker_ids = [0, 1, 2]
    units_per_step = 7  # K=7 > N=3

    ctx = StrategyContext(
        job_id="job-hetero",
        attempt_id="att-hetero",
        contract_hash="hash-contract",
        training_strategy="strict_bsp",
        expected_workers=expected_workers,
        update_policy="plain_sgd",
        dataset_build_id="build-hetero",
        dataset_manifest_hash="hash-dataset",
        parameter_manifest_hash="hash-param",
        protocol_version=1,
        total_numel=2,
        membership=tuple(Member(w, w + 10) for w in worker_ids),
    )

    registry = WorkerRegistry("att-hetero", expected_workers)
    for w in worker_ids:
        registry.register(w + 10, 0, w)

    # 14 Work Units total, K=7 -> 2 steps per epoch, 2 epochs total
    work_units = []
    for s in range(2):
        for b in range(7):
            work_units.append(WorkUnitRef(shard_id=s, batch_id=b, sample_count=32))

    batch_scheduler = BatchScheduler(
        work_units=work_units,
        training_seed=42,
        epochs=2,
        work_units_per_step=units_per_step,
        worker_ids=worker_ids,
    )
    workload_scheduler = WorkloadScheduler(
        policy="dbs",
        worker_ids=worker_ids,
        work_units_per_step=units_per_step,
    )

    initial_params = np.array([10.0, 20.0], dtype=np.float32)
    model = CanonicalModel(initial_params, 0, "hash-param")
    # Learning rate 0.1
    engine = UpdateEngine(model, "att-hetero", "plain_sgd", 0.1)
    events = EventEmitter("att-hetero", "job-hetero", capacity=100)

    snapshot_template = CheckpointSnapshot(
        checkpoint_id="tmpl",
        checkpoint_schema_version=1,
        job_id="job-hetero",
        created_by_attempt_id="att-hetero",
        contract_hash="hash-contract",
        checkpoint_policy="after_each_model_update_blocking",
        checkpoint_policy_version=1,
        training_strategy="strict_bsp",
        dataset_build_id="build-hetero",
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

    # Advance cluster to RUNNING
    coordinator.advance_initialization()
    for w in worker_ids:
        registry.transition(w, w + 10, SessionState.REGISTERING, 0)
    coordinator.advance_initialization()
    for w in worker_ids:
        registry.transition(w, w + 10, SessionState.PROVISIONING, 0)
        registry.transition(w, w + 10, SessionState.SHARD_READY, 0)
    coordinator.advance_initialization()
    for w in worker_ids:
        registry.transition(w, w + 10, SessionState.MODEL_SYNCING, 0)
        registry.transition(w, w + 10, SessionState.READY, 0)
    coordinator.advance_initialization()

    # Synthetic delays:
    # Worker 0: 40.0 ms per step (slowest)
    # Worker 1: 20.0 ms per step (medium)
    # Worker 2: 10.0 ms per step (fastest)
    worker_compute_times = {0: 40.0, 1: 20.0, 2: 10.0}

    # =========================================================================
    # EPOCH 0: Equal plan warm-up
    # =========================================================================
    assert workload_scheduler.current_epoch == 0
    plan0 = workload_scheduler.plan_for_epoch(0)
    assert plan0.policy == "equal"
    # With K=7 and 3 workers: 3 + 2 + 2 = 7 units
    assert sum(plan0.units_per_worker.values()) == 7
    assert plan0.units_per_worker == {0: 3, 1: 2, 2: 2}

    for step in range(2):
        op = coordinator.open_step()
        assert op.epoch == 0
        assert op.batch_ordinal == step
        # Invariant check: total units across all workers == K (7)
        total_units = sum(len(op.assignments[w].work_units) for w in worker_ids)
        assert total_units == units_per_step

        current_ver = op.input_model_version

        # All 3 workers submit contributions
        for w in worker_ids:
            assigned = op.assignments[w]
            # Gradient values: [1.0, 1.0] for worker 0, [2.0, 2.0] for 1, [3.0, 3.0] for 2
            grad = np.array([float(w + 1), float(w + 1)], dtype=np.float32)
            c = Contribution.from_gradient(
                grad,
                attempt_id="att-hetero",
                session_id=w + 10,
                worker_id=w,
                operation_id=op.operation_id,
                step_id=op.step_id,
                model_version=current_ver,
                shard_id=assigned.shard_id,
                batch_id=assigned.batch_id,
                batch_ordinal=step,
                sample_count=assigned.sample_count,
                parameter_manifest_hash="hash-param",
                tensor_id=1,
                compute_ms=worker_compute_times[w],
            )
            coordinator.admit(c)

        # N/N ParameterApplied ACK
        for w in worker_ids:
            coordinator.parameter_applied(
                ParameterApplied(
                    "att-hetero", w + 10, w, op.operation_id, op.step_id, current_ver + 1
                )
            )

        cp = coordinator.checkpoint()
        assert cp is not None
        assert cp.state == "COMPLETE"

    # =========================================================================
    # EPOCH 1: DBS dynamic batch allocation
    # =========================================================================
    assert workload_scheduler.current_epoch == 1
    plan1 = workload_scheduler.plan_for_epoch(1)
    assert plan1.policy == "dbs"

    # Invariant: K units total = 7
    assert sum(plan1.units_per_worker.values()) == 7

    # Verify dynamic allocation shifted units proportionally:
    # Worker 2 (fastest): received 4 units (increased from 2)
    # Worker 1 (medium): received 2 units
    # Worker 0 (slowest): received 1 unit (decreased from 3)
    assert plan1.units_per_worker[2] > plan1.units_per_worker[0]
    assert plan1.units_per_worker == {0: 1, 1: 2, 2: 4}

    # Verify telemetry event was emitted
    drained = events.drain()
    plan_events = [e for e in drained if e.event_type == "workload.plan_changed"]
    assert len(plan_events) == 1
    assert plan_events[0].details["epoch"] == 1
    assert plan_events[0].details["policy"] == "dbs"

    # Run Epoch 1 Step 0 under the DBS plan
    op1 = coordinator.open_step()
    assert op1.epoch == 1
    assert op1.batch_ordinal == 0

    # Verify assignment counts match the DBS plan exactly
    assert len(op1.assignments[0].work_units) == 1
    assert len(op1.assignments[1].work_units) == 2
    assert len(op1.assignments[2].work_units) == 4
    total_assigned_units = sum(len(op1.assignments[w].work_units) for w in worker_ids)
    assert total_assigned_units == units_per_step

    # Verify sample counts (32 samples per unit):
    # Worker 0: 32 samples
    # Worker 1: 64 samples
    # Worker 2: 128 samples
    # Total samples: 224
    assert op1.assignments[0].sample_count == 32
    assert op1.assignments[1].sample_count == 64
    assert op1.assignments[2].sample_count == 128

    ver_before = op1.input_model_version
    weights_before = model.snapshot().parameters.copy()

    # Submit contributions under DBS plan
    # Worker 0 submits g = [1.0, 1.0] (32 samples)
    # Worker 1 submits g = [2.0, 2.0] (64 samples)
    # Worker 2 submits g = [3.0, 3.0] (128 samples)
    # Weighted avg: (32*1.0 + 64*2.0 + 128*3.0) / 224 = 544 / 224 ≈ 2.4285714
    for w in worker_ids:
        assigned = op1.assignments[w]
        grad = np.array([float(w + 1), float(w + 1)], dtype=np.float32)
        c = Contribution.from_gradient(
            grad,
            attempt_id="att-hetero",
            session_id=w + 10,
            worker_id=w,
            operation_id=op1.operation_id,
            step_id=op1.step_id,
            model_version=ver_before,
            shard_id=assigned.shard_id,
            batch_id=assigned.batch_id,
            batch_ordinal=0,
            sample_count=assigned.sample_count,
            parameter_manifest_hash="hash-param",
            tensor_id=1,
            compute_ms=worker_compute_times[w],
        )
        coordinator.admit(c)

    for w in worker_ids:
        coordinator.parameter_applied(
            ParameterApplied("att-hetero", w + 10, w, op1.operation_id, op1.step_id, ver_before + 1)
        )

    cp1 = coordinator.checkpoint()
    assert cp1 is not None
    assert cp1.state == "COMPLETE"

    # Verify model parameters updated according to sample-weighted aggregation
    weights_after = np.frombuffer(model.snapshot().parameters, dtype=np.float32)
    expected_grad = 544.0 / 224.0
    expected_weights = np.frombuffer(weights_before, dtype=np.float32) - 0.1 * expected_grad
    np.testing.assert_allclose(weights_after, expected_weights, rtol=1e-5)
