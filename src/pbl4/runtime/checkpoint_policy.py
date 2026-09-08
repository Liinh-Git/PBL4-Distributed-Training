"""V1 durability policy; storage mechanics and Attempt transitions stay outside."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckpointPolicy:
    checkpoint_policy: str = "after_each_model_update_blocking"
    max_attempts: int = 3

    def __post_init__(self) -> None:
        if self.checkpoint_policy != "after_each_model_update_blocking":
            raise ValueError("Unsupported checkpoint policy")
        if type(self.max_attempts) is not int or self.max_attempts <= 0:
            raise ValueError("Invalid checkpoint attempt limit")

    def requires_checkpoint(
        self, *, update_completed: bool, synchronization_complete: bool
    ) -> bool:
        return update_completed and synchronization_complete

    def may_retry(self, attempts_made: int) -> bool:
        return 0 <= attempts_made < self.max_attempts

    def allows_commit(
        self, *, synchronization_complete: bool, checkpoint_state: str | None
    ) -> bool:
        return synchronization_complete and checkpoint_state == "COMPLETE"
