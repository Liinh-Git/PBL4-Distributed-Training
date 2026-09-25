"""Pure workload policy and discrete projection for Dynamic Batch Size (DBS).

Source: Q. Ye et al., "DBS: Dynamic Batch Size for Distributed Deep Neural
Network Training", arXiv:2007.11831.

This module is strictly pure: no PyTorch, database, HTTP, transport, or protocol
imports. It owns the mathematical formulation and discrete Work Unit allocation.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkerEpochStats:
    """Aggregated performance metrics of a worker across committed steps in an epoch."""

    worker_id: int
    sample_count: int
    compute_ms: float

    def __post_init__(self) -> None:
        if type(self.worker_id) is not int or self.worker_id < 0:
            raise ValueError("worker_id must be a non-negative integer")
        if type(self.sample_count) is not int or self.sample_count <= 0:
            raise ValueError("sample_count must be a positive integer")
        if (
            not isinstance(self.compute_ms, (int, float))
            or self.compute_ms <= 0
            or not math.isfinite(self.compute_ms)
        ):
            raise ValueError("compute_ms must be a positive finite number")


@dataclass(frozen=True, slots=True)
class WorkloadPlan:
    """Immutable workload allocation plan for an epoch."""

    epoch: int
    policy: str
    units_per_worker: dict[int, int]
    target_ratios: dict[int, float]

    def __post_init__(self) -> None:
        if type(self.epoch) is not int or self.epoch < 0:
            raise ValueError("epoch must be a non-negative integer")
        if self.policy not in {"equal", "dbs"}:
            raise ValueError(f"policy must be 'equal' or 'dbs', got {self.policy!r}")
        if not self.units_per_worker:
            raise ValueError("units_per_worker cannot be empty")
        if set(self.units_per_worker) != set(self.target_ratios):
            raise ValueError("units_per_worker and target_ratios must have identical worker keys")
        for w, k in self.units_per_worker.items():
            if type(w) is not int or w < 0:
                raise ValueError("Worker rank must be a non-negative integer")
            if type(k) is not int or k < 1:
                raise ValueError(f"Every worker must receive at least 1 unit, got {k} for rank {w}")
        for w, r in self.target_ratios.items():
            if not isinstance(r, (int, float)) or r <= 0 or not math.isfinite(r):
                raise ValueError(f"Target ratio for worker {w} must be positive and finite")


def project_units(ideal_units: dict[int, float], total_units: int) -> dict[int, int]:
    """Project continuous ideal Work Unit counts into a discrete integer partition.

    Constraints:
    - sum(k_i) == total_units
    - k_i >= 1 for all workers
    - Greedily minimizes the sum of squared errors sum((k_i - q_i)^2)
    - Deterministic tie-breaking favoring smaller worker_id
    """
    if type(total_units) is not int or total_units <= 0:
        raise ValueError("total_units must be a positive integer")
    if not ideal_units:
        raise ValueError("ideal_units cannot be empty")

    sorted_workers = sorted(ideal_units.keys())
    n = len(sorted_workers)
    if total_units < n:
        raise ValueError(
            f"total_units ({total_units}) must be at least worker count ({n}) "
            "to guarantee k_i >= 1 for all workers"
        )

    # 1. Initialize every worker with 1 Work Unit
    k: dict[int, int] = {w: 1 for w in sorted_workers}
    remaining = total_units - n

    # 2. Greedily allocate remaining units to minimize sum((k_i - q_i)^2)
    # The increase in squared error when assigning an additional unit to worker w is:
    # delta = (k[w] + 1 - q[w])^2 - (k[w] - q[w])^2 = 2 * (k[w] - q[w]) + 1
    for _ in range(remaining):
        best_worker = min(
            sorted_workers,
            key=lambda w: ((k[w] + 1 - ideal_units[w]) ** 2 - (k[w] - ideal_units[w]) ** 2, w),
        )
        k[best_worker] += 1

    return k


class EqualWorkloadPolicy:
    """Evenly partitions K Work Units among N workers with remainder to lower ranks."""

    @staticmethod
    def plan(epoch: int, worker_ids: Sequence[int], total_units: int) -> WorkloadPlan:
        if type(epoch) is not int or epoch < 0:
            raise ValueError("epoch must be a non-negative integer")
        if not worker_ids:
            raise ValueError("worker_ids cannot be empty")
        sorted_workers = sorted(set(worker_ids))
        if len(sorted_workers) != len(worker_ids):
            raise ValueError("Duplicate worker_ids provided")
        n = len(sorted_workers)
        if total_units < n:
            raise ValueError(
                f"total_units ({total_units}) must be >= worker count ({n}) for equal policy"
            )

        base = total_units // n
        remainder = total_units % n

        units: dict[int, int] = {}
        for idx, w in enumerate(sorted_workers):
            units[w] = base + (1 if idx < remainder else 0)

        ratios = {w: 1.0 / n for w in sorted_workers}
        return WorkloadPlan(
            epoch=epoch,
            policy="equal",
            units_per_worker=units,
            target_ratios=ratios,
        )


class DbsWorkloadPolicy:
    """Dynamic Batch Size allocation based on committed epoch statistics (arXiv:2007.11831)."""

    @staticmethod
    def plan(
        epoch: int,
        worker_ids: Sequence[int],
        total_units: int,
        stats: Sequence[WorkerEpochStats],
    ) -> WorkloadPlan:
        if type(epoch) is not int or epoch < 0:
            raise ValueError("epoch must be a non-negative integer")
        if not worker_ids:
            raise ValueError("worker_ids cannot be empty")
        sorted_workers = sorted(set(worker_ids))
        if len(sorted_workers) != len(worker_ids):
            raise ValueError("Duplicate worker_ids provided")
        n = len(sorted_workers)

        # DBS requires K > N so that adaptive reallocation is non-trivial
        if total_units <= n:
            raise ValueError(
                f"total_units ({total_units}) must be strictly greater than worker count ({n}) "
                "for dbs policy"
            )

        # Validate statistics completeness
        stats_map = {s.worker_id: s for s in stats}
        if len(stats_map) != len(stats):
            raise ValueError("Duplicate stats provided for the same worker")
        if set(stats_map) != set(sorted_workers):
            raise ValueError("Statistics worker set does not match active worker membership")

        total_samples = sum(s.sample_count for s in stats)
        if total_samples <= 0:
            raise ValueError("total_samples must be positive")

        # Compute throughput p_i = d_i / t_i
        # where d_i = samples_i / total_samples, t_i = compute_ms_i
        throughput: dict[int, float] = {}
        for w in sorted_workers:
            s = stats_map[w]
            d_i = s.sample_count / total_samples
            p_i = d_i / s.compute_ms
            if p_i <= 0 or not math.isfinite(p_i):
                raise ValueError(f"Invalid throughput calculation for worker {w}: {p_i}")
            throughput[w] = p_i

        p_sum = sum(throughput.values())
        if p_sum <= 0 or not math.isfinite(p_sum):
            raise ValueError("Total throughput sum must be positive and finite")

        # Normalized ratio r_i and continuous target q_i
        target_ratios: dict[int, float] = {}
        ideal_units: dict[int, float] = {}
        for w in sorted_workers:
            r_i = throughput[w] / p_sum
            target_ratios[w] = r_i
            ideal_units[w] = r_i * total_units

        # Discrete projection into integer units
        discrete_units = project_units(ideal_units, total_units)

        return WorkloadPlan(
            epoch=epoch,
            policy="dbs",
            units_per_worker=discrete_units,
            target_ratios=target_ratios,
        )
