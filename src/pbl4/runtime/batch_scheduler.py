"""Deterministic scheduling of global Work Units; never reshuffle samples within a unit."""

from collections.abc import Sequence
from dataclasses import dataclass

from pbl4.common.hashing import sha256_canonical_json
from pbl4.runtime.synchronization.context import BatchAssignment, WorkUnitRef
from pbl4.runtime.workload_policy import EqualWorkloadPolicy, WorkloadPlan


@dataclass(frozen=True, slots=True)
class RecoveryCursor:
    epoch: int
    next_batch_ordinal: int


class BatchScheduler:
    """A pure mapping from a recovery cursor to global Work Unit assignments.

    Hash ordering fixes the permutation independently of Python/NumPy RNG versions.
    Coordinator advances the cursor only after its progression gates succeed.
    """

    def __init__(
        self,
        work_units: Sequence[WorkUnitRef | BatchAssignment],
        training_seed: int,
        epochs: int,
        work_units_per_step: int | None = None,
        worker_ids: Sequence[int] | None = None,
    ):
        if type(training_seed) is not int or type(epochs) is not int or epochs <= 0:
            raise ValueError("Invalid training seed or epoch count")

        if not work_units:
            raise ValueError("No physical batches / work units provided")

        self._seed = training_seed
        self._epochs = epochs

        # Determine if legacy mode applies (for backward compatibility during migration)
        is_legacy = (
            work_units_per_step is None
            and worker_ids is None
            and all(isinstance(x, BatchAssignment) for x in work_units)
        )

        if is_legacy:
            by_worker: dict[int, dict[int, BatchAssignment]] = {}
            for batch in work_units:
                assert isinstance(batch, BatchAssignment)
                worker = by_worker.setdefault(batch.worker_id, {})
                if batch.batch_id in worker:
                    raise ValueError("Duplicate physical batch")
                worker[batch.batch_id] = batch
            ids = set(next(iter(by_worker.values())))
            if any(set(worker) != ids for worker in by_worker.values()):
                raise ValueError("Workers must have the same physical batch ID set")
            self._is_legacy = True
            self._ids = tuple(sorted(ids))
            self._by_worker = by_worker
            self._steps_per_epoch = len(self._ids)
            self._k = len(by_worker)
            self._catalog = tuple(
                WorkUnitRef(b.shard_id, b.batch_id, b.sample_count)
                for worker in by_worker.values()
                for b in worker.values()
            )
        else:
            self._is_legacy = False
            catalog_list: list[WorkUnitRef] = []
            inferred_workers: set[int] = set()

            for item in work_units:
                if isinstance(item, WorkUnitRef):
                    catalog_list.append(item)
                elif isinstance(item, BatchAssignment):
                    inferred_workers.add(item.worker_id)
                    catalog_list.extend(item.work_units)
                else:
                    raise ValueError(
                        f"Expected WorkUnitRef or BatchAssignment, got {type(item).__name__}"
                    )

            catalog_list.sort(key=lambda u: (u.shard_id, u.batch_id))
            identities = {(u.shard_id, u.batch_id) for u in catalog_list}
            if len(identities) != len(catalog_list):
                raise ValueError("Duplicate physical batch / work unit identity in catalog")

            self._catalog = tuple(catalog_list)
            if work_units_per_step is not None:
                if type(work_units_per_step) is not int or work_units_per_step <= 0:
                    raise ValueError("work_units_per_step must be a positive integer")
                self._k = work_units_per_step
            elif inferred_workers:
                self._k = len(inferred_workers)
            else:
                self._k = 1

            if len(self._catalog) < self._k:
                raise ValueError(
                    f"Not enough work units in catalog ({len(self._catalog)}) "
                    f"for a single step (K={self._k})"
                )

            self._steps_per_epoch = len(self._catalog) // self._k
            if self._steps_per_epoch < 1:
                raise ValueError(
                    "Catalog must provide at least one complete step (steps_per_epoch >= 1)"
                )

            if worker_ids is not None:
                self._default_worker_ids = tuple(sorted(set(worker_ids)))
            elif inferred_workers:
                self._default_worker_ids = tuple(sorted(inferred_workers))
            else:
                self._default_worker_ids = tuple(range(self._k))

    @property
    def steps_per_epoch(self) -> int:
        return self._steps_per_epoch

    @property
    def work_units_per_step(self) -> int:
        return self._k

    @property
    def eligible_work_units(self) -> tuple[WorkUnitRef, ...]:
        return self._catalog

    def _validate_cursor(self, cursor: RecoveryCursor) -> None:
        if (
            type(cursor.epoch) is not int
            or type(cursor.next_batch_ordinal) is not int
            or not 0 <= cursor.epoch <= self._epochs
            or not 0 <= cursor.next_batch_ordinal < self._steps_per_epoch
            or (cursor.epoch == self._epochs and cursor.next_batch_ordinal != 0)
        ):
            raise ValueError("Invalid recovery cursor")

    def _get_epoch_units(self, epoch: int) -> list[WorkUnitRef]:
        """Compute the deterministic permutation of catalog Work Units for a given epoch."""
        return sorted(
            self._catalog,
            key=lambda u: sha256_canonical_json([self._seed, epoch, u.shard_id, u.batch_id]),
        )

    def assignments(
        self,
        cursor: RecoveryCursor,
        plan: WorkloadPlan | None = None,
    ) -> tuple[BatchAssignment, ...]:
        self._validate_cursor(cursor)
        if cursor.epoch == self._epochs:
            raise StopIteration("Training schedule exhausted")

        if self._is_legacy and plan is None:
            ordered = sorted(
                self._ids,
                key=lambda batch_id: sha256_canonical_json([self._seed, cursor.epoch, batch_id]),
            )
            batch_id = ordered[cursor.next_batch_ordinal]
            return tuple(
                BatchAssignment(
                    worker_id,
                    worker[batch_id].shard_id,
                    batch_id,
                    cursor.next_batch_ordinal,
                    worker[batch_id].sample_count,
                )
                for worker_id, worker in sorted(self._by_worker.items())
            )

        epoch_units = self._get_epoch_units(cursor.epoch)
        start_idx = cursor.next_batch_ordinal * self._k
        step_units = epoch_units[start_idx : start_idx + self._k]

        if plan is None:
            plan = EqualWorkloadPolicy.plan(
                epoch=cursor.epoch,
                worker_ids=self._default_worker_ids,
                total_units=self._k,
            )

        if sum(plan.units_per_worker.values()) != self._k:
            raise ValueError(
                f"WorkloadPlan units ({sum(plan.units_per_worker.values())}) must equal "
                f"work_units_per_step ({self._k})"
            )

        sorted_workers = sorted(plan.units_per_worker.keys())
        assignments = []
        offset = 0
        for w in sorted_workers:
            k_i = plan.units_per_worker[w]
            w_units = tuple(step_units[offset : offset + k_i])
            offset += k_i
            assignments.append(
                BatchAssignment(
                    worker_id=w,
                    batch_ordinal=cursor.next_batch_ordinal,
                    work_units=w_units,
                    sample_count=sum(u.sample_count for u in w_units),
                )
            )

        return tuple(assignments)

    def next_cursor(self, cursor: RecoveryCursor) -> RecoveryCursor:
        self._validate_cursor(cursor)
        if cursor.epoch == self._epochs:
            raise StopIteration("Training schedule exhausted")
        ordinal = cursor.next_batch_ordinal + 1
        if ordinal == self._steps_per_epoch:
            return RecoveryCursor(cursor.epoch + 1, 0)
        return RecoveryCursor(cursor.epoch, ordinal)
