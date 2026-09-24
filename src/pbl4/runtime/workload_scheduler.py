"""WorkloadScheduler manages in-memory WorkloadPlan progression and metric accumulation.

Follows canonical rules (docs/DBS_DESIGN.md §7, §12, docs/DBS_IMPLEMENTATION_PLAN.md.md §6):
- Strictly pure in-memory runtime component: no DB, HTTP, or transport calls.
- Ingests metrics ONLY from COMMITTED contributions.
- Transitions plans exclusively at epoch boundaries.
- Handles warm-up on fresh starts and checkpoint resumes.
"""

import math
from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from pbl4.runtime.contribution import Contribution
from pbl4.runtime.workload_policy import (
    DbsWorkloadPolicy,
    EqualWorkloadPolicy,
    WorkerEpochStats,
    WorkloadPlan,
)


class WorkloadScheduler:
    """Manages in-memory WorkloadPlan per epoch and collects committed training metrics."""

    def __init__(
        self,
        policy: str,
        worker_ids: Sequence[int],
        work_units_per_step: int,
    ) -> None:
        if policy not in {"equal", "dbs"}:
            raise ValueError(f"policy must be 'equal' or 'dbs', got {policy!r}")
        if not worker_ids:
            raise ValueError("worker_ids cannot be empty")
        sorted_workers = sorted(set(worker_ids))
        if len(sorted_workers) != len(worker_ids):
            raise ValueError("Duplicate worker_ids provided")
        if type(work_units_per_step) is not int or work_units_per_step <= 0:
            raise ValueError("work_units_per_step must be a positive integer")
        if policy == "equal" and work_units_per_step < len(sorted_workers):
            raise ValueError("work_units_per_step must be >= worker count for equal policy")
        if policy == "dbs" and work_units_per_step <= len(sorted_workers):
            raise ValueError("work_units_per_step must be > worker count for dbs policy")

        self._policy = policy
        self._worker_ids = tuple(sorted_workers)
        self._k = work_units_per_step

        self._current_epoch: int = 0
        self._plans: dict[int, WorkloadPlan] = {}
        # epoch -> worker_id -> accumulated sample_count
        self._epoch_samples: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        # epoch -> worker_id -> accumulated compute_ms
        self._epoch_compute_ms: dict[int, dict[int, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self._collect_stats: bool = True
        self._resumed_mid_epoch: bool = False

    @property
    def policy(self) -> str:
        return self._policy

    @property
    def worker_ids(self) -> tuple[int, ...]:
        return self._worker_ids

    @property
    def work_units_per_step(self) -> int:
        return self._k

    @property
    def collect_stats(self) -> bool:
        return self._collect_stats

    @property
    def current_epoch(self) -> int:
        return self._current_epoch

    def plan_for_epoch(self, epoch: int) -> WorkloadPlan:
        """Return the immutable WorkloadPlan for the specified epoch."""
        if type(epoch) is not int or epoch < 0:
            raise ValueError("epoch must be a non-negative integer")

        self._current_epoch = epoch
        if epoch in self._plans:
            return self._plans[epoch]

        # For epoch 0 or equal policy, plan is always Equal
        if self._policy == "equal" or epoch == 0:
            plan = EqualWorkloadPolicy.plan(epoch, self._worker_ids, self._k)
            self._plans[epoch] = plan
            return plan

        # For DBS policy epoch > 0, attempt to build DBS plan from previous epoch stats
        plan = self._compute_dbs_plan(epoch)
        self._plans[epoch] = plan
        return plan

    def _compute_dbs_plan(self, epoch: int) -> WorkloadPlan:
        prev_epoch = epoch - 1
        samples = self._epoch_samples.get(prev_epoch, {})
        times = self._epoch_compute_ms.get(prev_epoch, {})

        missing_workers = set(self._worker_ids) - set(samples.keys())
        if missing_workers:
            raise ValueError(
                f"Cannot compute DBS plan for epoch {epoch}: missing sample stats "
                f"for workers {sorted(missing_workers)}"
            )
        missing_times = set(self._worker_ids) - set(times.keys())
        if missing_times:
            raise ValueError(
                f"Cannot compute DBS plan for epoch {epoch}: missing compute_ms stats "
                f"for workers {sorted(missing_times)}"
            )

        stats = [
            WorkerEpochStats(w, samples[w], times[w])
            for w in self._worker_ids
        ]
        return DbsWorkloadPolicy.plan(epoch, self._worker_ids, self._k, stats)

    def record_committed(
        self,
        contributions: Sequence[Contribution],
        epoch: int | None = None,
    ) -> None:
        """Record performance statistics from COMMITTED contributions."""
        if not self._collect_stats:
            return
        if not contributions:
            return

        target_epoch = self._current_epoch if epoch is None else epoch
        if type(target_epoch) is not int or target_epoch < 0:
            raise ValueError("epoch must be a non-negative integer")

        for c in contributions:
            if c.worker_id not in self._worker_ids:
                raise ValueError(f"Contribution worker_id {c.worker_id} not in membership")
            if (
                not isinstance(c.compute_ms, (int, float))
                or c.compute_ms <= 0
                or not math.isfinite(c.compute_ms)
            ):
                raise ValueError(
                    f"Invalid compute_ms for worker {c.worker_id}: {c.compute_ms}. "
                    "Must be a positive finite number."
                )
            if type(c.sample_count) is not int or c.sample_count <= 0:
                raise ValueError(
                    f"Invalid sample_count for worker {c.worker_id}: {c.sample_count}. "
                    "Must be a positive integer."
                )

            self._epoch_samples[target_epoch][c.worker_id] += c.sample_count
            self._epoch_compute_ms[target_epoch][c.worker_id] += float(c.compute_ms)

    def on_epoch_completed(self, epoch: int) -> WorkloadPlan:
        """Invoked at epoch completion to transition active plan for next epoch."""
        if type(epoch) is not int or epoch < 0:
            raise ValueError("epoch must be a non-negative integer")

        next_epoch = epoch + 1
        self._current_epoch = next_epoch

        if self._policy == "equal":
            next_plan = EqualWorkloadPolicy.plan(next_epoch, self._worker_ids, self._k)
            self._plans[next_epoch] = next_plan
            return next_plan

        # DBS policy:
        if self._resumed_mid_epoch:
            # Partial resumed epoch completed. Discard partial stats, enable collection
            # for next full epoch, and run next full epoch with Equal plan.
            self._resumed_mid_epoch = False
            self._collect_stats = True
            next_plan = EqualWorkloadPolicy.plan(next_epoch, self._worker_ids, self._k)
            self._plans[next_epoch] = next_plan
            return next_plan

        if not self._collect_stats:
            # Stats collection was disabled; enable it now and run next epoch with Equal
            self._collect_stats = True
            next_plan = EqualWorkloadPolicy.plan(next_epoch, self._worker_ids, self._k)
            self._plans[next_epoch] = next_plan
            return next_plan

        # Compute DBS plan using full stats from completed epoch
        next_plan = self._compute_dbs_plan(next_epoch)
        self._plans[next_epoch] = next_plan
        return next_plan

    def reset_after_resume(self, cursor: Any) -> None:
        """Reset warm-up and stats collection state following a checkpoint restore."""
        epoch = int(cursor.epoch)
        ordinal = int(cursor.next_batch_ordinal)

        self._current_epoch = epoch
        # Resumed epoch always uses Equal plan
        self._plans[epoch] = EqualWorkloadPolicy.plan(epoch, self._worker_ids, self._k)

        self._epoch_samples[epoch].clear()
        self._epoch_compute_ms[epoch].clear()

        if ordinal == 0:
            # Boundary resume: full epoch ahead, enable stats collection
            self._collect_stats = True
            self._resumed_mid_epoch = False
        else:
            # Mid-epoch resume: partial epoch ahead, disable stats collection
            self._collect_stats = False
            self._resumed_mid_epoch = True
