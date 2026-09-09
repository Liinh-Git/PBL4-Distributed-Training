"""Canonical state with one bound update writer and immutable snapshots."""

from dataclasses import dataclass
from threading import RLock

import numpy as np


@dataclass(frozen=True, slots=True)
class ModelSnapshot:
    model_version: int
    parameter_manifest_hash: str
    _parameters: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "_parameters", bytes(self._parameters))
        if type(self.model_version) is not int or self.model_version < 0:
            raise ValueError("Invalid model version")
        if not self._parameters or len(self._parameters) % 4:
            raise ValueError("Invalid FP32 parameter vector")
        if not np.isfinite(self.parameters).all():
            raise ValueError("Nonfinite parameters")

    @property
    def parameters(self) -> np.ndarray:
        return np.frombuffer(self._parameters, dtype=np.float32)


class CanonicalModel:
    """Construction accepts initial/verified restored state; publication is private.

    Lock order is UpdateEngine -> CanonicalModel. Readers only take the model
    lock. Neither owner executes external I/O while holding these locks.
    """

    def __init__(self, parameters: np.ndarray, model_version: int, parameter_manifest_hash: str):
        values = np.asarray(parameters)
        if values.dtype != np.float32 or values.ndim != 1:
            raise ValueError("Expected flat FP32 parameters")
        self._state = ModelSnapshot(model_version, parameter_manifest_hash, values.tobytes())
        self._lock = RLock()
        self._writer: object | None = None

    def snapshot(self) -> ModelSnapshot:
        with self._lock:
            return self._state

    def _bind_writer(self, writer: object) -> None:
        with self._lock:
            if self._writer is not None:
                raise ValueError("CanonicalModel already has an update owner")
            self._writer = writer

    def _publish(self, writer: object, previous: ModelSnapshot, candidate: ModelSnapshot) -> None:
        with self._lock:
            if writer is not self._writer or self._writer is None:
                raise PermissionError("Only the bound UpdateEngine may publish")
            if self._state is not previous:
                raise ValueError("Stale canonical snapshot")
            if (
                candidate.model_version != previous.model_version + 1
                or candidate.parameter_manifest_hash != previous.parameter_manifest_hash
                or candidate.parameters.shape != previous.parameters.shape
            ):
                raise ValueError("Invalid canonical publication")
            self._state = candidate
