"""Model Catalog — canonical V1 supported model profiles and metadata provider port.

CANONICAL REFERENCES:
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- docs/IMPLEMENTATION_CONTRACT.md

V1 SPECIFICATION:
- Strictly supports model_id = "resnet18_groupnorm"
- Profile = "RESNET18_GROUPNORM_V1"
- Backend must resolve canonical model metadata via ModelMetadataProvider port.
- If authoritative parameter_manifest_hash is not available in isolated branch,
  validation / freeze must fail closed.
- Tests may inject FakeModelMetadataProvider.
"""

from __future__ import annotations

import os
from typing import Any, Protocol

CANONICAL_MODEL_ID = "resnet18_groupnorm"
CANONICAL_MODEL_PROFILE = "RESNET18_GROUPNORM_V1"

_V1_MODELS: dict[str, dict[str, Any]] = {
    CANONICAL_MODEL_ID: {
        "model_id": CANONICAL_MODEL_ID,
        "profile": CANONICAL_MODEL_PROFILE,
        "display_name": "ResNet-18 (GroupNorm)",
        "description": (
            "ResNet-18 architecture with Group Normalization (GroupNorm) replacing BatchNorm "
            "for distributed Parameter Server training stability across workers."
        ),
        "supported_tasks": ["image_classification"],
        "default_optimizer": "plain_sgd_without_momentum",
        "default_checkpoint_cadence": "after_each_model_update_blocking",
        "input_shape": [3, 32, 32],
        "num_classes": 10,
    }
}


def get_model(model_id: str) -> dict[str, Any] | None:
    """Return model definition if present in catalog, else None."""
    return _V1_MODELS.get(model_id)


def list_models() -> list[dict[str, Any]]:
    """Return all available model definitions in the catalog."""
    return list(_V1_MODELS.values())


def validate_model_id(model_id: str) -> dict[str, Any]:
    """Validate model_id against canonical catalog.

    Raises ValueError if model_id is not in catalog.
    """
    model = get_model(model_id)
    if model is None:
        supported = ", ".join(f"'{m}'" for m in _V1_MODELS)
        raise ValueError(f"Unsupported model_id '{model_id}'. V1 only supports: {supported}.")
    return model


def is_supported_model(model_id: str) -> bool:
    """Return True if model_id or its canonical profile is supported."""
    return model_id in _V1_MODELS or model_id == CANONICAL_MODEL_PROFILE


get_model_spec = get_model
list_supported_models = list_models


# ─── Model Metadata Provider Port ─────────────────────────────────────────────


class ModelMetadataProvider(Protocol):
    """Port for resolving canonical model metadata without importing torch/adapter."""

    def get_model_metadata(self, model_id: str) -> dict[str, Any] | None:
        """Return dict with model_id, profile, parameter_manifest_hash or None."""
        ...


class DefaultModelMetadataProvider:
    """Production provider reading canonical catalog and authoritative manifest hash from env.

    If authoritative parameter_manifest_hash is not configured in the environment,
    it returns None for the hash, causing contract resolution / freeze to fail closed.
    """

    def get_model_metadata(self, model_id: str) -> dict[str, Any] | None:
        spec = get_model(model_id)
        if spec is None:
            return None
        # Check if an authoritative parameter manifest hash is injected via env
        env_hash = os.environ.get("CANONICAL_PARAMETER_MANIFEST_HASH") or os.environ.get(
            f"PARAMETER_MANIFEST_HASH_{model_id.upper()}"
        )
        return {
            "model_id": spec["model_id"],
            "profile": spec["profile"],
            "parameter_manifest_hash": env_hash or None,
            "input_shape": spec["input_shape"],
            "num_classes": spec["num_classes"],
            "default_optimizer": spec["default_optimizer"],
            "default_checkpoint_cadence": spec["default_checkpoint_cadence"],
        }


class FakeModelMetadataProvider:
    """Testing provider that supplies a deterministic valid parameter_manifest_hash."""

    def __init__(
        self,
        parameter_manifest_hash: str = (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        ),
    ) -> None:
        self.parameter_manifest_hash = parameter_manifest_hash

    def get_model_metadata(self, model_id: str) -> dict[str, Any] | None:
        spec = get_model(model_id)
        if spec is None:
            return None
        return {
            "model_id": spec["model_id"],
            "profile": spec["profile"],
            "parameter_manifest_hash": self.parameter_manifest_hash,
            "input_shape": spec["input_shape"],
            "num_classes": spec["num_classes"],
            "default_optimizer": spec["default_optimizer"],
            "default_checkpoint_cadence": spec["default_checkpoint_cadence"],
        }


_current_provider: ModelMetadataProvider = DefaultModelMetadataProvider()


def get_model_metadata_provider() -> ModelMetadataProvider:
    return _current_provider


def set_model_metadata_provider(provider: ModelMetadataProvider) -> None:
    global _current_provider
    _current_provider = provider
