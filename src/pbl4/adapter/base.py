"""Framework boundary for local compute and canonical parameter application."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from pbl4.protocol.parameter_manifest import ParameterManifest


@dataclass(frozen=True, slots=True)
class TensorBundle:
    parameter_manifest_hash: str
    tensors: tuple[np.ndarray, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.parameter_manifest_hash, str)
            or len(self.parameter_manifest_hash) != 64
            or not self.tensors
        ):
            raise ValueError("Invalid tensor bundle identity")
        owned = []
        for value in self.tensors:
            array = np.asarray(value)
            if array.dtype != np.float32 or not array.size or not np.isfinite(array).all():
                raise ValueError("Tensor bundle requires finite nonempty FP32 arrays")
            array = array.copy()
            array.setflags(write=False)
            owned.append(array)
        object.__setattr__(self, "tensors", tuple(owned))


@dataclass(frozen=True, slots=True)
class LocalGradient:
    loss: float
    bundle: TensorBundle
    sample_count: int

    def __post_init__(self) -> None:
        if (
            not np.isfinite(self.loss)
            or type(self.sample_count) is not int
            or self.sample_count <= 0
        ):
            raise ValueError("Invalid local gradient metadata")


class ModelAdapter(ABC):
    @property
    @abstractmethod
    def manifest(self) -> ParameterManifest: ...

    @abstractmethod
    def export_parameters(self) -> TensorBundle: ...

    @abstractmethod
    def apply_parameters(self, bundle: TensorBundle) -> None: ...

    @abstractmethod
    def compute_loss_and_gradients(self, x: np.ndarray, y: np.ndarray) -> LocalGradient:
        """Return gradients averaged over the local batch, not summed gradients."""
        ...
