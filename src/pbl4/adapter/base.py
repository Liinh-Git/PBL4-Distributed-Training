"""Framework boundary for local compute and canonical parameter application."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np

from pbl4.common.hashing import sha256_canonical_json


@dataclass(frozen=True, slots=True)
class ParameterSpec:
    tensor_id: int
    name: str
    shape: tuple[int, ...]
    dtype: str
    numel: int
    byte_offset: int
    byte_length: int

    def value(self) -> dict[str, object]:
        return {
            "tensor_id": self.tensor_id,
            "name": self.name,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "numel": self.numel,
            "byte_offset": self.byte_offset,
            "byte_length": self.byte_length,
        }


@dataclass(frozen=True, slots=True)
class ParameterManifest:
    schema_version: int
    tensors: tuple[ParameterSpec, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "tensors", tuple(self.tensors))
        if type(self.schema_version) is not int or self.schema_version <= 0:
            raise ValueError("Invalid Parameter Manifest schema version")
        offset = 0
        for tensor_id, tensor in enumerate(self.tensors):
            if (
                tensor.tensor_id != tensor_id
                or not tensor.name
                or tensor.dtype != "float32"
                or not tensor.shape
                or any(dimension <= 0 for dimension in tensor.shape)
                or tensor.numel != int(np.prod(tensor.shape))
                or tensor.byte_offset != offset
                or tensor.byte_length != tensor.numel * 4
            ):
                raise ValueError("Invalid Parameter Manifest")
            offset += tensor.byte_length
        if not self.tensors:
            raise ValueError("Empty Parameter Manifest")

    @property
    def parameter_manifest_hash(self) -> str:
        return sha256_canonical_json(
            {
                "schema_version": self.schema_version,
                "tensors": [tensor.value() for tensor in self.tensors],
            }
        )

    @property
    def total_numel(self) -> int:
        return sum(tensor.numel for tensor in self.tensors)


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
