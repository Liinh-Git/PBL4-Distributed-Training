"""Completed, owned gradients. Transport integrity is validated before this boundary."""

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True, slots=True)
class Contribution:
    attempt_id: str
    session_id: int
    worker_id: int
    operation_id: int
    step_id: int
    model_version: int
    shard_id: int
    batch_id: int
    batch_ordinal: int
    sample_count: int
    parameter_manifest_hash: str
    tensor_id: int
    _gradient_bytes: bytes = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "_gradient_bytes", bytes(self._gradient_bytes))
        if not self._gradient_bytes or len(self._gradient_bytes) % np.dtype(np.float32).itemsize:
            raise ValueError("A complete nonempty FP32 gradient is required")
        if not np.isfinite(self.gradient).all():
            raise ValueError("Nonfinite gradient")

    @classmethod
    def from_gradient(cls, gradient: np.ndarray, **identity: object) -> "Contribution":
        """Detach a complete flat FP32 vector from every writable producer alias."""
        values = np.asarray(gradient)
        if values.dtype != np.float32 or values.ndim != 1 or not values.size:
            raise ValueError("Expected a nonempty flat FP32 vector")
        return cls(**identity, _gradient_bytes=values.tobytes())

    @property
    def gradient(self) -> np.ndarray:
        """Native in-process storage; this is not a tensor wire codec."""
        return np.frombuffer(self._gradient_bytes, dtype=np.float32)

    @property
    def logical_key(self) -> tuple[str, int, int]:
        """StrictBSP logical identity is independent of connection identity."""
        return self.attempt_id, self.step_id, self.worker_id
