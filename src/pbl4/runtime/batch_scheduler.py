"""Deterministic scheduling of pinned physical batches; never reshuffle samples."""

from dataclasses import dataclass

from pbl4.common.hashing import sha256_canonical_json
from pbl4.runtime.synchronization.context import BatchAssignment


@dataclass(frozen=True, slots=True)
class RecoveryCursor:
    epoch: int
    next_batch_ordinal: int


class BatchScheduler:
    """A pure mapping from a recovery cursor to assignments.

    Hash ordering fixes the permutation independently of Python/NumPy RNG versions.
    Coordinator advances the cursor only after its progression gates succeed.
    """

    def __init__(self, batches: tuple[BatchAssignment, ...], training_seed: int, epochs: int):
        if type(training_seed) is not int or type(epochs) is not int or epochs <= 0:
            raise ValueError("Invalid training seed or epoch count")
        self._batches = tuple(batches)
        self._seed = training_seed
        self._epochs = epochs
        by_worker: dict[int, dict[int, BatchAssignment]] = {}
        for batch in self._batches:
            worker = by_worker.setdefault(batch.worker_id, {})
            if batch.batch_id in worker:
                raise ValueError("Duplicate physical batch")
            worker[batch.batch_id] = batch
        if not by_worker:
            raise ValueError("No physical batches")
        ids = set(next(iter(by_worker.values())))
        if any(set(worker) != ids for worker in by_worker.values()):
            raise ValueError("Workers must have the same physical batch ID set")
        self._ids = tuple(sorted(ids))
        self._by_worker = by_worker

    def _validate_cursor(self, cursor: RecoveryCursor) -> None:
        if (
            type(cursor.epoch) is not int
            or type(cursor.next_batch_ordinal) is not int
            or not 0 <= cursor.epoch <= self._epochs
            or not 0 <= cursor.next_batch_ordinal < len(self._ids)
            or (cursor.epoch == self._epochs and cursor.next_batch_ordinal != 0)
        ):
            raise ValueError("Invalid recovery cursor")

    def assignments(self, cursor: RecoveryCursor) -> tuple[BatchAssignment, ...]:
        self._validate_cursor(cursor)
        if cursor.epoch == self._epochs:
            raise StopIteration("Training schedule exhausted")
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

    def next_cursor(self, cursor: RecoveryCursor) -> RecoveryCursor:
        self._validate_cursor(cursor)
        if cursor.epoch == self._epochs:
            raise StopIteration("Training schedule exhausted")
        ordinal = cursor.next_batch_ordinal + 1
        if ordinal == len(self._ids):
            return RecoveryCursor(cursor.epoch + 1, 0)
        return RecoveryCursor(cursor.epoch, ordinal)
