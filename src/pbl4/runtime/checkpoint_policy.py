"""V1 durability policy; storage mechanics and Attempt transitions stay outside."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckpointPolicy:
    every_n_epochs: int
    checkpoint_policy: str = "periodic"
    policy_version: int = 1
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.checkpoint_policy != "periodic":
            raise ValueError("Unsupported checkpoint policy")
        if self.policy_version != 1:
            raise ValueError("Unsupported checkpoint policy version")
        if type(self.every_n_epochs) is not int or self.every_n_epochs <= 0:
            raise ValueError("every_n_epochs must be a positive integer")
        if type(self.max_attempts) is not int or self.max_attempts <= 0:
            raise ValueError("Invalid checkpoint attempt limit")

    def due_epoch(self, completed_epoch: int) -> bool:
        return completed_epoch > 0 and completed_epoch % self.every_n_epochs == 0

    def may_retry(self, attempts_made: int) -> bool:
        return 0 <= attempts_made < self.max_attempts

