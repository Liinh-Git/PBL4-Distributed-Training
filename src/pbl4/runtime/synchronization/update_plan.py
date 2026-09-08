"""Immutable contribution selection for generic aggregation and update services."""

from dataclasses import dataclass

from pbl4.runtime.contribution import Contribution


@dataclass(frozen=True, slots=True)
class UpdatePlan:
    attempt_id: str
    training_strategy: str
    operation_id: int
    step_id: int
    input_model_version: int
    update_policy: str
    contributions: tuple[Contribution, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "contributions", tuple(self.contributions))
        if not self.contributions:
            raise ValueError("Empty contribution selection")
        keys = [c.logical_key for c in self.contributions]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate contribution selection")
        for c in self.contributions:
            if (c.attempt_id, c.operation_id, c.step_id, c.model_version) != (
                self.attempt_id,
                self.operation_id,
                self.step_id,
                self.input_model_version,
            ):
                raise ValueError("Contribution does not belong to this update")
            if type(c.sample_count) is not int or c.sample_count <= 0:
                raise ValueError("Invalid sample count")

    @property
    def identity(self) -> tuple[str, str, int]:
        return self.attempt_id, self.training_strategy, self.operation_id

    @property
    def total_sample_count(self) -> int:
        return sum(c.sample_count for c in self.contributions)
