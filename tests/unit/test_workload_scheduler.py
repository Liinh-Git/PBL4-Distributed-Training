"""Unit tests for WorkloadScheduler runtime state and DBS transitions."""

import numpy as np
import pytest

from pbl4.runtime.batch_scheduler import RecoveryCursor
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.workload_scheduler import WorkloadScheduler


def _dummy_contribution(
    worker_id: int,
    sample_count: int,
    compute_ms: float,
    epoch: int = 0,
    ordinal: int = 0,
) -> Contribution:
    grad = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
    return Contribution.from_gradient(
        grad,
        attempt_id="att-1",
        session_id=worker_id + 1,
        worker_id=worker_id,
        operation_id=ordinal,
        step_id=ordinal,
        model_version=0,
        shard_id=0,
        batch_id=1,
        batch_ordinal=ordinal,
        sample_count=sample_count,
        parameter_manifest_hash="hash",
        tensor_id=1,
        compute_ms=compute_ms,
    )


def test_workload_scheduler_equal_policy() -> None:
    scheduler = WorkloadScheduler(
        policy="equal",
        worker_ids=[0, 1, 2],
        work_units_per_step=6,
    )
    assert scheduler.policy == "equal"
    assert scheduler.worker_ids == (0, 1, 2)
    assert scheduler.work_units_per_step == 6

    # Epoch 0 is equal
    plan0 = scheduler.plan_for_epoch(0)
    assert plan0.policy == "equal"
    assert plan0.units_per_worker == {0: 2, 1: 2, 2: 2}

    # Record some stats
    scheduler.record_committed([
        _dummy_contribution(0, 64, 100.0),
        _dummy_contribution(1, 64, 50.0),
        _dummy_contribution(2, 64, 200.0),
    ])

    # On epoch completed, epoch 1 is still equal
    plan1 = scheduler.on_epoch_completed(0)
    assert plan1.policy == "equal"
    assert plan1.units_per_worker == {0: 2, 1: 2, 2: 2}


def test_workload_scheduler_dbs_transition_epoch_0_to_1() -> None:
    # 2 workers, K=4 units per step
    scheduler = WorkloadScheduler(
        policy="dbs",
        worker_ids=[0, 1],
        work_units_per_step=4,
    )

    # Epoch 0 is Equal: 2 units each
    plan0 = scheduler.plan_for_epoch(0)
    assert plan0.policy == "equal"
    assert plan0.units_per_worker == {0: 2, 1: 2}
    assert scheduler.collect_stats is True

    # Record 2 committed steps in epoch 0
    # Worker 0: 200 total samples, 200.0 ms total compute -> throughput = 1.0 s/ms
    # Worker 1: 200 total samples, 100.0 ms total compute -> throughput = 2.0 s/ms (2x faster)
    scheduler.record_committed([
        _dummy_contribution(0, 100, 100.0, epoch=0, ordinal=0),
        _dummy_contribution(1, 100, 50.0, epoch=0, ordinal=0),
    ])
    scheduler.record_committed([
        _dummy_contribution(0, 100, 100.0, epoch=0, ordinal=1),
        _dummy_contribution(1, 100, 50.0, epoch=0, ordinal=1),
    ])

    # Epoch 0 completed -> transition to Epoch 1
    plan1 = scheduler.on_epoch_completed(0)
    assert plan1.policy == "dbs"
    # r0 = 1/3 -> q0 = 1.33, r1 = 2/3 -> q1 = 2.67
    # Discrete projection with sum=4, k >= 1: {0: 1, 1: 3}
    assert plan1.units_per_worker == {0: 1, 1: 3}


def test_workload_scheduler_rejects_invalid_stats() -> None:
    scheduler = WorkloadScheduler(
        policy="dbs",
        worker_ids=[0, 1],
        work_units_per_step=4,
    )
    scheduler.plan_for_epoch(0)

    # compute_ms == 0.0 (allowed in legacy Contribution, rejected in DBS record_committed)
    bad_c1 = _dummy_contribution(0, 32, 0.0)
    with pytest.raises(ValueError, match="compute_ms"):
        scheduler.record_committed([bad_c1])

    # Unknown worker ID rejected
    bad_worker = _dummy_contribution(99, 32, 100.0)
    with pytest.raises(ValueError, match="not in membership"):
        scheduler.record_committed([bad_worker])

    # Negative compute_ms rejected at Contribution boundary
    with pytest.raises(ValueError, match="compute_ms"):
        _dummy_contribution(0, 32, -10.0)


def test_workload_scheduler_boundary_resume() -> None:
    scheduler = WorkloadScheduler(
        policy="dbs",
        worker_ids=[0, 1],
        work_units_per_step=4,
    )

    # Boundary resume at epoch 1, next_batch_ordinal=0
    cursor = RecoveryCursor(epoch=1, next_batch_ordinal=0)
    scheduler.reset_after_resume(cursor)

    assert scheduler.current_epoch == 1
    assert scheduler.collect_stats is True
    plan1 = scheduler.plan_for_epoch(1)
    assert plan1.policy == "equal"
    assert plan1.units_per_worker == {0: 2, 1: 2}

    # Record stats during epoch 1
    scheduler.record_committed([
        _dummy_contribution(0, 100, 200.0, epoch=1),
        _dummy_contribution(1, 100, 100.0, epoch=1),
    ])

    # Transition to epoch 2: should use DBS!
    plan2 = scheduler.on_epoch_completed(1)
    assert plan2.policy == "dbs"
    assert plan2.units_per_worker == {0: 1, 1: 3}


def test_workload_scheduler_mid_epoch_resume() -> None:
    scheduler = WorkloadScheduler(
        policy="dbs",
        worker_ids=[0, 1],
        work_units_per_step=4,
    )

    # Mid-epoch resume at epoch 1, next_batch_ordinal=2
    cursor = RecoveryCursor(epoch=1, next_batch_ordinal=2)
    scheduler.reset_after_resume(cursor)

    assert scheduler.current_epoch == 1
    assert scheduler.collect_stats is False

    # Recording during remainder of epoch 1 is ignored
    scheduler.record_committed([
        _dummy_contribution(0, 100, 200.0, epoch=1),
        _dummy_contribution(1, 100, 100.0, epoch=1),
    ])

    # End of partial epoch 1: next epoch 2 must be Equal and enable stats collection
    plan2 = scheduler.on_epoch_completed(1)
    assert plan2.policy == "equal"
    assert scheduler.collect_stats is True

    # Record full stats in epoch 2
    scheduler.record_committed([
        _dummy_contribution(0, 100, 200.0, epoch=2),
        _dummy_contribution(1, 100, 100.0, epoch=2),
    ])

    # End of full epoch 2: epoch 3 transitions to DBS!
    plan3 = scheduler.on_epoch_completed(2)
    assert plan3.policy == "dbs"
    assert plan3.units_per_worker == {0: 1, 1: 3}
