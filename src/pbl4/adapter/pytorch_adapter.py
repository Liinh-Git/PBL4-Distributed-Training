"""PyTorch local model interaction with no optimizer or wire-format ownership."""

import math
from collections.abc import Callable
from typing import Literal

import numpy as np
import torch
from torch import nn

from pbl4.adapter.base import (
    LocalGradient,
    ModelAdapter,
    TensorBundle,
)
from pbl4.protocol.constants import PARAMETER_MANIFEST_SCHEMA_VERSION
from pbl4.protocol.parameter_manifest import ParameterEntry, ParameterManifest


class PyTorchAdapter(ModelAdapter):
    def __init__(
        self,
        model: nn.Module,
        loss: Callable[[torch.Tensor, torch.Tensor], torch.Tensor],
        manifest_schema_version: int = 1,
        *,
        local_gradient_reduction: Literal["mean"],
    ):
        if local_gradient_reduction != "mean":
            raise ValueError(
                f"PyTorchAdapter only supports local_gradient_reduction='mean' for "
                f"correct distributed weighted aggregation; got {local_gradient_reduction!r}"
            )
        if manifest_schema_version != PARAMETER_MANIFEST_SCHEMA_VERSION:
            raise ValueError("Unsupported Parameter Manifest schema version")
        self._model = model
        self._loss = loss
        self._local_gradient_reduction = local_gradient_reduction
        specs = []
        offset = 0
        for tensor_id, (name, parameter) in enumerate(model.named_parameters()):
            if parameter.dtype != torch.float32 or not parameter.numel():
                raise ValueError("Model parameters must be nonempty float32 tensors")
            numel = parameter.numel()
            specs.append(
                ParameterEntry(
                    tensor_id, name, tuple(parameter.shape), "float32", numel, offset, numel * 4
                )
            )
            offset += numel * 4
        self._manifest = ParameterManifest.create(specs)

    @property
    def manifest(self) -> ParameterManifest:
        return self._manifest

    def _bundle(self, tensors: list[np.ndarray]) -> TensorBundle:
        return TensorBundle(self.manifest.parameter_manifest_hash, tuple(tensors))

    def export_parameters(self) -> TensorBundle:
        return self._bundle(
            [parameter.detach().cpu().numpy().copy() for parameter in self._model.parameters()]
        )

    def apply_parameters(self, bundle: TensorBundle) -> None:
        prepared = self._validate_bundle(bundle)
        parameters = tuple(self._model.parameters())
        previous = tuple(parameter.detach().clone() for parameter in parameters)
        try:
            with torch.no_grad():
                for parameter, candidate in zip(parameters, prepared, strict=True):
                    parameter.copy_(candidate)
        except Exception:
            with torch.no_grad():
                for parameter, old in zip(parameters, previous, strict=True):
                    parameter.copy_(old)
            raise

    def compute_loss_and_gradients(self, x: np.ndarray, y: np.ndarray) -> LocalGradient:
        if (
            x.dtype != np.float32
            or x.ndim != 4
            or not len(x)
            or y.dtype != np.int64
            or y.shape != (len(x),)
            or not np.isfinite(x).all()
        ):
            raise ValueError("Invalid local image-classification batch")
        self._model.zero_grad(set_to_none=True)
        device = next(self._model.parameters()).device
        inputs = torch.from_numpy(np.ascontiguousarray(x)).to(device)
        labels = torch.from_numpy(np.ascontiguousarray(y)).to(device)
        value = self._loss(self._model(inputs), labels)
        if value.ndim != 0 or not torch.isfinite(value):
            raise ValueError("Loss must be one finite scalar")
        value.backward()
        gradients = []
        for parameter in self._model.parameters():
            if parameter.grad is None:
                raise ValueError("Every canonical parameter must have a gradient")
            gradients.append(parameter.grad.detach().cpu().numpy().copy())
        loss_value = float(value.detach().cpu())
        if not math.isfinite(loss_value):
            raise ValueError("Nonfinite loss")
        return LocalGradient(loss_value, self._bundle(gradients), len(x))

    def _validate_bundle(self, bundle: TensorBundle) -> tuple[torch.Tensor, ...]:
        if bundle.parameter_manifest_hash != self.manifest.parameter_manifest_hash or len(
            bundle.tensors
        ) != len(self.manifest.parameters):
            raise ValueError("Parameter Manifest mismatch")
        device = next(self._model.parameters()).device
        candidates = []
        for value, spec in zip(bundle.tensors, self.manifest.parameters, strict=True):
            if (
                value.dtype != np.float32
                or value.shape != spec.shape
                or not np.isfinite(value).all()
            ):
                raise ValueError("Malformed canonical parameter tensor")
            candidates.append(torch.from_numpy(np.array(value, copy=True, order="C")).to(device))
        return tuple(candidates)
