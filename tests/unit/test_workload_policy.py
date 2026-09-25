"""Comprehensive unit tests for pure DBS workload policy and discrete projection."""

import pytest

from pbl4.runtime.workload_policy import (
    DbsWorkloadPolicy,
    EqualWorkloadPolicy,
    WorkerEpochStats,
    project_units,
)


def test_paper_appendix_a_golden_projection():
    """Verify normative golden test from arXiv:2007.11831 Appendix A.

    Given ideal continuous allocations [13.7, 16.5, 19.6, 14.2] summing to 64,
    the discrete error minimization projection MUST produce [14, 16, 20, 14].
    """
    ideal = {0: 13.7, 1: 16.5, 2: 19.6, 3: 14.2}
    total_units = 64
    result = project_units(ideal, total_units)

    expected = {0: 14, 1: 16, 2: 20, 3: 14}
    assert result == expected
    assert sum(result.values()) == total_units


def test_project_units_single_worker():
    ideal = {0: 10.0}
    result = project_units(ideal, 10)
    assert result == {0: 10}


def test_project_units_minimum_k_equals_n():
    ideal = {0: 1.0, 1: 1.0, 2: 1.0}
    result = project_units(ideal, 3)
    assert result == {0: 1, 1: 1, 2: 1}


def test_project_units_rejects_insufficient_units():
    ideal = {0: 1.0, 1: 1.0, 2: 1.0}
    with pytest.raises(ValueError, match="at least worker count"):
        project_units(ideal, 2)


def test_project_units_deterministic_tie_breaking():
    # Two workers have identical ideal allocation (5.5 each), total units = 11.
    # Worker 0 should receive the extra unit because worker_id 0 < 1.
    ideal = {0: 5.5, 1: 5.5}
    result = project_units(ideal, 11)
    assert result == {0: 6, 1: 5}


def test_project_units_extreme_skew_preserves_minimum_one():
    # Worker 0 is 1000x faster than Worker 1.
    # Ideal: {0: 99.9, 1: 0.1}, total_units = 100.
    ideal = {0: 99.9, 1: 0.1}
    result = project_units(ideal, 100)
    assert result[1] >= 1
    assert result == {0: 99, 1: 1}
    assert sum(result.values()) == 100


def test_equal_policy_exact_division():
    plan = EqualWorkloadPolicy.plan(epoch=0, worker_ids=[0, 1, 2], total_units=9)
    assert plan.epoch == 0
    assert plan.policy == "equal"
    assert plan.units_per_worker == {0: 3, 1: 3, 2: 3}
    assert plan.target_ratios == {0: 1 / 3, 1: 1 / 3, 2: 1 / 3}


def test_equal_policy_remainder_distribution():
    # 10 units among 3 workers: 4, 3, 3 (extra unit to lowest rank 0)
    plan = EqualWorkloadPolicy.plan(epoch=1, worker_ids=[2, 0, 1], total_units=10)
    assert plan.units_per_worker == {0: 4, 1: 3, 2: 3}
    assert sum(plan.units_per_worker.values()) == 10


def test_equal_policy_k_equals_n():
    plan = EqualWorkloadPolicy.plan(epoch=0, worker_ids=[0, 1, 2], total_units=3)
    assert plan.units_per_worker == {0: 1, 1: 1, 2: 1}


def test_equal_policy_rejects_k_less_than_n():
    with pytest.raises(ValueError, match="must be >= worker count"):
        EqualWorkloadPolicy.plan(epoch=0, worker_ids=[0, 1, 2], total_units=2)


def test_dbs_policy_rejects_k_less_than_or_equal_n():
    stats = [
        WorkerEpochStats(0, 100, 1000.0),
        WorkerEpochStats(1, 100, 1000.0),
        WorkerEpochStats(2, 100, 1000.0),
    ]
    with pytest.raises(ValueError, match="strictly greater than worker count"):
        DbsWorkloadPolicy.plan(epoch=1, worker_ids=[0, 1, 2], total_units=3, stats=stats)


def test_dbs_policy_equal_performance():
    # Workers with identical sample_count and compute_ms get balanced allocation
    stats = [
        WorkerEpochStats(0, 1000, 5000.0),
        WorkerEpochStats(1, 1000, 5000.0),
        WorkerEpochStats(2, 1000, 5000.0),
    ]
    plan = DbsWorkloadPolicy.plan(epoch=1, worker_ids=[0, 1, 2], total_units=12, stats=stats)
    assert plan.policy == "dbs"
    assert plan.units_per_worker == {0: 4, 1: 4, 2: 4}
    assert pytest.approx(plan.target_ratios[0]) == 1 / 3


def test_dbs_policy_heterogeneous_speed_ratio_1_2_4():
    # Worker 0 takes 4000ms, Worker 1 takes 2000ms, Worker 2 takes 1000ms for same samples
    # Throughput ratios are 1 : 2 : 4 -> r_i = 1/7, 2/7, 4/7
    # For total_units = 14: ideal is [2.0, 4.0, 8.0]
    stats = [
        WorkerEpochStats(0, 1000, 4000.0),
        WorkerEpochStats(1, 1000, 2000.0),
        WorkerEpochStats(2, 1000, 1000.0),
    ]
    plan = DbsWorkloadPolicy.plan(epoch=1, worker_ids=[0, 1, 2], total_units=14, stats=stats)
    assert plan.units_per_worker == {0: 2, 1: 4, 2: 8}
    assert pytest.approx(plan.target_ratios[0]) == 1 / 7
    assert pytest.approx(plan.target_ratios[1]) == 2 / 7
    assert pytest.approx(plan.target_ratios[2]) == 4 / 7


def test_dbs_policy_validation_errors():
    valid_stats = [
        WorkerEpochStats(0, 100, 1000.0),
        WorkerEpochStats(1, 100, 1000.0),
    ]

    # Missing worker in stats
    with pytest.raises(ValueError, match="does not match active worker membership"):
        DbsWorkloadPolicy.plan(epoch=1, worker_ids=[0, 1, 2], total_units=6, stats=valid_stats)

    # Duplicate worker in stats
    duplicate_stats = [
        WorkerEpochStats(0, 100, 1000.0),
        WorkerEpochStats(0, 100, 1000.0),
    ]
    with pytest.raises(ValueError, match="Duplicate stats"):
        DbsWorkloadPolicy.plan(epoch=1, worker_ids=[0, 1], total_units=6, stats=duplicate_stats)

    # Invalid stat fields
    with pytest.raises(ValueError, match="sample_count must be a positive integer"):
        WorkerEpochStats(0, 0, 1000.0)

    with pytest.raises(ValueError, match="compute_ms must be a positive finite number"):
        WorkerEpochStats(0, 100, 0.0)

    with pytest.raises(ValueError, match="compute_ms must be a positive finite number"):
        WorkerEpochStats(0, 100, float("nan"))

    with pytest.raises(ValueError, match="compute_ms must be a positive finite number"):
        WorkerEpochStats(0, 100, float("inf"))
