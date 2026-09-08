"""Model Catalog — canonical V1 supported model profiles.

CANONICAL REFERENCES:
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- docs/IMPLEMENTATION_CONTRACT.md

V1 SPECIFICATION:
- Strictly supports model_id = "resnet18_groupnorm"
- Profile = "RESNET18_GROUPNORM_V1"
- No other models (small_cnn, resnet18_gn, etc.) are permitted in V1.
"""

from __future__ import annotations

from typing import Any

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
