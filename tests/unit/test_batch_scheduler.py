"""Comprehensive unit tests for the Work Unit BatchScheduler."""

import pytest

from pbl4.runtime.batch_scheduler import BatchScheduler, RecoveryCursor
from pbl4.runtime.synchronization.context import WorkUnitRef
from pbl4.runtime.workload_policy import EqualWorkloadPolicy, WorkloadPlan


def _make_catalog(m: int, sample_count: int = 16) -> tuple[WorkUnitRef, ...]:
    return tuple(
        WorkUnitRef(shard_id=i // 10, batch_id=i % 10, sample_count=sample_count) for i in range(m)
    )


def test_batch_scheduler_validation():
    # Empty
    with pytest.raises(ValueError, match="No physical batches"):
        BatchScheduler([], 42, 1, 3)

    # Invalid seed/epochs
    catalog = _make_catalog(10)
    with pytest.raises(ValueError, match="Invalid training seed or epoch count"):
        BatchScheduler(catalog, 42, 0, 3)

    with pytest.raises(ValueError, match="Invalid training seed or epoch count"):
        BatchScheduler(catalog, "42", 1, 3)  # type: ignore

    # Insufficient units for K
    with pytest.raises(ValueError, match="Not enough work units"):
        BatchScheduler(catalog, 42, 1, 15)

    # Duplicate work unit identities
    duplicates = [WorkUnitRef(0, 1, 10), WorkUnitRef(0, 1, 10)]
    with pytest.raises(ValueError, match="Duplicate"):
        BatchScheduler(duplicates, 42, 1, 1)


def test_batch_scheduler_drop_last_and_uniqueness():
    # 25 units, K = 6 -> steps_per_epoch = 4 (24 units used, 1 dropped)
    catalog = _make_catalog(25)
    scheduler = BatchScheduler(catalog, training_seed=1234, epochs=2, work_units_per_step=6)
    assert scheduler.steps_per_epoch == 4
    assert scheduler.work_units_per_step == 6

    plan = EqualWorkloadPolicy.plan(epoch=0, worker_ids=[0, 1, 2], total_units=6)

    cursor = RecoveryCursor(epoch=0, next_batch_ordinal=0)
    used_units_epoch_0: list[WorkUnitRef] = []

    for _ in range(scheduler.steps_per_epoch):
        assignments = scheduler.assignments(cursor, plan)
        assert len(assignments) == 3
        step_units = [u for a in assignments for u in a.work_units]
        assert len(step_units) == 6
        # Ensure no duplicates within a step
        assert len(set(step_units)) == 6
        used_units_epoch_0.extend(step_units)
        cursor = scheduler.next_cursor(cursor)

    assert len(used_units_epoch_0) == 24
    # All 24 units in epoch 0 must be unique (drop_last drops the 25th)
    assert len(set(used_units_epoch_0)) == 24
    assert cursor == RecoveryCursor(epoch=1, next_batch_ordinal=0)


def test_equal_and_dbs_select_identical_global_k_units():
    """Core DBS Invariant: Equal and DBS policies MUST process the exact same

    global K units at any given step; only the worker partitioning differs.
    """
    catalog = _make_catalog(30)
    scheduler = BatchScheduler(catalog, training_seed=999, epochs=3, work_units_per_step=6)
    cursor = RecoveryCursor(epoch=1, next_batch_ordinal=2)

    # Equal plan: 2 units per worker for 3 workers
    equal_plan = WorkloadPlan(
        epoch=1,
        policy="equal",
        units_per_worker={0: 2, 1: 2, 2: 2},
        target_ratios={0: 1 / 3, 1: 1 / 3, 2: 1 / 3},
    )

    # DBS plan: heterogeneous distribution (1, 2, 3 units) summing to K=6
    dbs_plan = WorkloadPlan(
        epoch=1,
        policy="dbs",
        units_per_worker={0: 1, 1: 2, 2: 3},
        target_ratios={0: 1 / 6, 1: 2 / 6, 2: 3 / 6},
    )

    equal_assignments = scheduler.assignments(cursor, equal_plan)
    dbs_assignments = scheduler.assignments(cursor, dbs_plan)

    equal_units = [u for a in equal_assignments for u in a.work_units]
    dbs_units = [u for a in dbs_assignments for u in a.work_units]

    # Global set of Work Units must be IDENTICAL in both content and order
    assert equal_units == dbs_units
    assert len(equal_units) == 6

    # Verify worker counts match plans
    assert [len(a.work_units) for a in equal_assignments] == [2, 2, 2]
    assert [len(a.work_units) for a in dbs_assignments] == [1, 2, 3]


def test_batch_scheduler_reproducibility():
    catalog = _make_catalog(18)
    s1 = BatchScheduler(catalog, training_seed=42, epochs=2, work_units_per_step=6)
    s2 = BatchScheduler(catalog, training_seed=42, epochs=2, work_units_per_step=6)

    cursor = RecoveryCursor(epoch=1, next_batch_ordinal=1)
    assert s1.assignments(cursor) == s2.assignments(cursor)


def test_batch_scheduler_schedule_exhaustion():
    catalog = _make_catalog(12)
    scheduler = BatchScheduler(catalog, training_seed=42, epochs=1, work_units_per_step=4)
    assert scheduler.steps_per_epoch == 3

    cursor = RecoveryCursor(epoch=0, next_batch_ordinal=0)
    for _ in range(3):
        cursor = scheduler.next_cursor(cursor)

    assert cursor == RecoveryCursor(epoch=1, next_batch_ordinal=0)

    # Schedule exhausted
    with pytest.raises(StopIteration, match="Training schedule exhausted"):
        scheduler.assignments(cursor)

    with pytest.raises(StopIteration, match="Training schedule exhausted"):
        scheduler.next_cursor(cursor)


def test_batch_scheduler_plan_k_mismatch():
    catalog = _make_catalog(12)
    scheduler = BatchScheduler(catalog, training_seed=42, epochs=1, work_units_per_step=4)
    cursor = RecoveryCursor(epoch=0, next_batch_ordinal=0)

    # Plan with sum(k_i) == 5 != 4
    invalid_plan = WorkloadPlan(
        epoch=0,
        policy="equal",
        units_per_worker={0: 3, 1: 2},
        target_ratios={0: 0.6, 1: 0.4},
    )
    with pytest.raises(ValueError, match="must equal work_units_per_step"):
        scheduler.assignments(cursor, invalid_plan)
