"""Immutable contract, membership and assignment values for synchronization."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pbl4.common.work_unit import WorkUnitRef


@dataclass(frozen=True, slots=True)
class Member:
    worker_id: int
    session_id: int

    def __post_init__(self) -> None:
        if type(self.worker_id) is not int or self.worker_id < 0:
            raise ValueError("Invalid Worker rank")
        if type(self.session_id) is not int or not 0 < self.session_id < 2**63:
            raise ValueError("Invalid active session")


@dataclass(frozen=True, slots=True, init=False)
class BatchAssignment:
    """Workload assignment for a single worker in a synchronized step.

    Supports both multiple WorkUnitRef assignments and legacy single-batch
    signatures for backward compatibility during migration.
    """

    worker_id: int
    batch_ordinal: int
    work_units: tuple[WorkUnitRef, ...]
    sample_count: int

    def __init__(
        self,
        worker_id: int,
        *args: Any,
        batch_ordinal: int | None = None,
        work_units: Sequence[WorkUnitRef] | None = None,
        sample_count: int | None = None,
        shard_id: int | None = None,
        batch_id: int | None = None,
    ) -> None:
        if len(args) == 4:
            # Legacy 5 positional args: (worker_id, shard_id, batch_id, batch_ordinal, sample_count)
            s_id, b_id, b_ord, s_count = args
            units = (WorkUnitRef(s_id, b_id, s_count),)
            resolved_batch_ordinal = b_ord
            resolved_sample_count = s_count
        elif len(args) == 3:
            # 4 positional args: (worker_id, batch_ordinal, work_units, sample_count)
            resolved_batch_ordinal, raw_units, s_count = args
            units = tuple(raw_units)
            resolved_sample_count = s_count
        elif len(args) == 2:
            # 3 positional args: (worker_id, batch_ordinal, work_units)
            resolved_batch_ordinal, raw_units = args
            units = tuple(raw_units)
            resolved_sample_count = sum(u.sample_count for u in units)
        elif work_units is not None:
            # Keyword invocation with work_units
            if batch_ordinal is None:
                raise ValueError("batch_ordinal is required")
            resolved_batch_ordinal = batch_ordinal
            units = tuple(work_units)
            resolved_sample_count = (
                sample_count if sample_count is not None else sum(u.sample_count for u in units)
            )
        elif shard_id is not None and batch_id is not None:
            # Legacy keyword invocation
            if batch_ordinal is None or sample_count is None:
                raise ValueError(
                    "batch_ordinal and sample_count are required for legacy assignment"
                )
            units = (WorkUnitRef(shard_id, batch_id, sample_count),)
            resolved_batch_ordinal = batch_ordinal
            resolved_sample_count = sample_count
        else:
            raise ValueError("Invalid BatchAssignment arguments")

        if type(worker_id) is not int or worker_id < 0:
            raise ValueError("Invalid assignment identity")
        if type(resolved_batch_ordinal) is not int or resolved_batch_ordinal < 0:
            raise ValueError("Invalid assignment identity")

        if not units:
            raise ValueError("work_units cannot be empty")
        for u in units:
            if not isinstance(u, WorkUnitRef):
                raise ValueError(f"Expected WorkUnitRef in work_units, got {type(u).__name__}")

        identities = {(u.shard_id, u.batch_id) for u in units}
        if len(identities) != len(units):
            raise ValueError("Duplicate (shard_id, batch_id) in the same BatchAssignment")

        expected_samples = sum(u.sample_count for u in units)
        if type(resolved_sample_count) is not int or resolved_sample_count <= 0:
            raise ValueError("Invalid sample count")
        if resolved_sample_count != expected_samples:
            raise ValueError(
                f"sample_count ({resolved_sample_count}) must equal sum of WorkUnit "
                f"sample counts ({expected_samples})"
            )

        object.__setattr__(self, "worker_id", worker_id)
        object.__setattr__(self, "batch_ordinal", resolved_batch_ordinal)
        object.__setattr__(self, "work_units", units)
        object.__setattr__(self, "sample_count", resolved_sample_count)

    @property
    def shard_id(self) -> int:
        return self.work_units[0].shard_id

    @property
    def batch_id(self) -> int:
        return self.work_units[0].batch_id


@dataclass(frozen=True, slots=True)
class StrategyContext:
    job_id: str
    attempt_id: str
    contract_hash: str
    training_strategy: str
    expected_workers: int
    update_policy: str
    dataset_build_id: str
    dataset_manifest_hash: str
    parameter_manifest_hash: str
    protocol_version: int
    total_numel: int
    membership: tuple[Member, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "membership", tuple(self.membership))
        if type(self.expected_workers) is not int or self.expected_workers <= 0:
            raise ValueError("expected_workers must be a positive integer")
        if len(self.membership) != self.expected_workers:
            raise ValueError("Membership cardinality differs from resolved contract")
        if len({m.worker_id for m in self.membership}) != self.expected_workers:
            raise ValueError("Duplicate logical rank")
        if len({m.session_id for m in self.membership}) != self.expected_workers:
            raise ValueError("Duplicate active session")
        if type(self.total_numel) is not int or self.total_numel <= 0:
            raise ValueError("Invalid manifest total_numel")
        if type(self.protocol_version) is not int or self.protocol_version != 1:
            raise ValueError("Unsupported protocol version")


@dataclass(frozen=True, slots=True)
class OperationContext:
    operation_id: int
    step_id: int
    epoch: int
    batch_ordinal: int
    input_model_version: int
    assignments: tuple[BatchAssignment, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "assignments", tuple(self.assignments))
        for value in (
            self.operation_id,
            self.step_id,
            self.epoch,
            self.batch_ordinal,
            self.input_model_version,
        ):
            if type(value) is not int or value < 0:
                raise ValueError("Operation identities and cursors must be nonnegative integers")
