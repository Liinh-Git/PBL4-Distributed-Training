"""Immutable representation of a physical batch Work Unit."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkUnitRef:
    """Immutable identity and metadata of a physical batch Work Unit."""

    shard_id: int
    batch_id: int
    sample_count: int

    def __post_init__(self) -> None:
        for val in (self.shard_id, self.batch_id):
            if type(val) is not int or val < 0:
                raise ValueError("shard_id and batch_id must be non-negative integers")
        if type(self.sample_count) is not int or self.sample_count <= 0:
            raise ValueError("sample_count must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "shard_id": self.shard_id,
            "batch_id": self.batch_id,
            "sample_count": self.sample_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WorkUnitRef":
        return cls(
            shard_id=int(data["shard_id"]),  # type: ignore[arg-type]
            batch_id=int(data["batch_id"]),  # type: ignore[arg-type]
            sample_count=int(data["sample_count"]),  # type: ignore[arg-type]
        )
