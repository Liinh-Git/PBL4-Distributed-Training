"""Async occurrence accounting. Its owner serializes dispatch, commit and reclaim."""

from collections import deque
from dataclasses import dataclass

from pbl4.common.hashing import sha256_canonical_json
from pbl4.common.work_unit import WorkUnitRef


@dataclass(frozen=True, slots=True)
class AsyncAssignment:
    worker_id: int
    session_id: int
    operation_id: int
    model_version: int
    epoch: int
    indices: tuple[int, ...]
    work_units: tuple[WorkUnitRef, ...]
    started_at: float


class GlobalWorkUnitPool:
    def __init__(self, units, seed: int, epochs: int, units_per_contribution: int):
        self.units = tuple(sorted(units, key=lambda u: (u.shard_id, u.batch_id)))
        if not self.units or len({(u.shard_id, u.batch_id) for u in self.units}) != len(self.units):
            raise ValueError("A nonempty unique Work Unit catalog is required")
        if any(type(v) is not int or v <= 0 for v in (epochs, units_per_contribution)):
            raise ValueError("Invalid async workload size")
        self.seed, self.epochs, self.k = seed, epochs, units_per_contribution
        self.target = epochs * len(self.units)
        self.catalog_hash = sha256_canonical_json([seed, epochs, [u.to_dict() for u in self.units]])
        self.issued = 0
        self.remaining: set[int] = set()
        self.pending: deque[int] = deque()
        self.assignments: dict[int, AsyncAssignment] = {}
        self.counts = dict.fromkeys(
            ("applied_units", "dropped_units", "applied_samples", "dropped_samples"), 0
        )
        self._next_operation = 1
        self._epoch = -1
        self._ordered = ()

    def unit(self, index: int) -> WorkUnitRef:
        epoch, offset = divmod(index, len(self.units))
        if epoch != self._epoch:
            self._ordered = tuple(
                sorted(
                    self.units,
                    key=lambda u: sha256_canonical_json([self.seed, epoch, u.shard_id, u.batch_id]),
                )
            )
            self._epoch = epoch
        return self._ordered[offset]

    @property
    def frontier(self) -> int:
        return min(self.remaining, default=self.issued) // len(self.units)

    @property
    def finished(self) -> bool:
        return self.issued == self.target and not self.remaining

    def new_operation_id(self) -> int:
        """Allocate an identity for either an assignment or an idle offer."""
        operation = self._next_operation
        self._next_operation += 1
        return operation

    def assign(self, worker_id: int, session_id: int, version: int, now: float):
        if worker_id in self.assignments:
            return None
        first = self.pending[0] if self.pending else self.issued
        if first == self.target:
            return None
        epoch = first // len(self.units)
        indices = []
        while len(indices) < self.k:
            candidate = self.pending[0] if self.pending else self.issued
            if candidate >= self.target or candidate // len(self.units) != epoch:
                break
            if self.pending:
                self.pending.popleft()
            else:
                self.issued += 1
                self.remaining.add(candidate)
            indices.append(candidate)
        assignment = AsyncAssignment(
            worker_id,
            session_id,
            self.new_operation_id(),
            version,
            epoch,
            tuple(indices),
            tuple(self.unit(i) for i in indices),
            now,
        )
        self.assignments[worker_id] = assignment
        return assignment

    def complete(self, assignment: AsyncAssignment, applied: bool) -> None:
        if self.assignments.get(assignment.worker_id) != assignment:
            raise ValueError("Assignment is not active")
        for index in assignment.indices:
            self.remaining.remove(index)
        del self.assignments[assignment.worker_id]
        prefix = "applied" if applied else "dropped"
        self.counts[f"{prefix}_units"] += len(assignment.indices)
        self.counts[f"{prefix}_samples"] += sum(u.sample_count for u in assignment.work_units)

    def reclaim(self, worker_id: int, session_id: int) -> bool:
        assignment = self.assignments.get(worker_id)
        if assignment is None or assignment.session_id != session_id:
            return False
        del self.assignments[worker_id]
        self.pending.extend(assignment.indices)
        return True

    def snapshot(self) -> dict:
        return {
            "catalog_hash": self.catalog_hash,
            "issued": self.issued,
            "remaining": sorted(self.remaining),
            **self.counts,
        }

    def restore(self, value: dict) -> None:
        expected = set(self.snapshot())
        if (
            not isinstance(value, dict)
            or set(value) != expected
            or value["catalog_hash"] != self.catalog_hash
        ):
            raise ValueError("Async recovery catalog/fields mismatch")
        issued, remaining = value["issued"], value["remaining"]
        if (
            type(issued) is not int
            or not 0 <= issued <= self.target
            or not isinstance(remaining, list)
        ):
            raise ValueError("Invalid async recovery position")
        if any(type(i) is not int or not 0 <= i < issued for i in remaining) or len(
            set(remaining)
        ) != len(remaining):
            raise ValueError("Invalid async recovery outstanding work")
        counts = {k: value[k] for k in self.counts}
        if any(type(v) is not int or v < 0 for v in counts.values()):
            raise ValueError("Invalid async recovery counters")
        if counts["applied_units"] + counts["dropped_units"] != issued - len(remaining):
            raise ValueError("Async recovery unit accounting mismatch")
        smallest = min(u.sample_count for u in self.units)
        largest = max(u.sample_count for u in self.units)
        for prefix in ("applied", "dropped"):
            size, samples = counts[f"{prefix}_units"], counts[f"{prefix}_samples"]
            if not smallest * size <= samples <= largest * size:
                raise ValueError("Async recovery outcome sample accounting mismatch")
        epochs, tail = divmod(issued, len(self.units))
        expected_samples = epochs * sum(u.sample_count for u in self.units)
        expected_samples += sum(
            self.unit(epochs * len(self.units) + i).sample_count for i in range(tail)
        )
        expected_samples -= sum(self.unit(i).sample_count for i in remaining)
        if counts["applied_samples"] + counts["dropped_samples"] != expected_samples:
            raise ValueError("Async recovery sample accounting mismatch")
        self.issued, self.remaining = issued, set(remaining)
        self.pending = deque(sorted(remaining))
        self.assignments.clear()
        self.counts = counts
