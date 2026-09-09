"""Immutable contract, membership and assignment values for synchronization."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Member:
    worker_id: int
    session_id: int

    def __post_init__(self) -> None:
        if type(self.worker_id) is not int or self.worker_id < 0:
            raise ValueError("Invalid Worker rank")
        if type(self.session_id) is not int or not 0 < self.session_id < 2**63:
            raise ValueError("Invalid active session")


@dataclass(frozen=True, slots=True)
class BatchAssignment:
    worker_id: int
    shard_id: int
    batch_id: int
    batch_ordinal: int
    sample_count: int

    def __post_init__(self) -> None:
        for value in (self.worker_id, self.shard_id, self.batch_id, self.batch_ordinal):
            if type(value) is not int or value < 0:
                raise ValueError("Invalid assignment identity")
        if type(self.sample_count) is not int or self.sample_count <= 0:
            raise ValueError("Invalid sample count")


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
