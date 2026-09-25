"""Unit tests verifying that contract_resolver preserves all preprocessing fields

from the Dataset Build without dropping fields or inventing normalization values.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pbl4.management_backend.app import create_app
from pbl4.management_backend.services.contract_resolver import (
    ContractResolutionError,
    resolve,
)
from pbl4.management_backend.services.model_catalog import (
    FakeModelMetadataProvider,
    get_model_metadata_provider,
    set_model_metadata_provider,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def setup_fake_model_metadata():
    orig = get_model_metadata_provider()
    set_model_metadata_provider(FakeModelMetadataProvider())
    yield
    set_model_metadata_provider(orig)


@pytest.fixture
def app_client():
    from pbl4.management_backend import db
    from pbl4.management_backend.config import get_settings

    db.close_pool()
    settings = get_settings()
    with patch.object(settings, "database_url", None), patch.object(db, "init_pool"):
        db.close_pool()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        db.close_pool()


# ─── Contract Resolver Preprocessing Preservation Tests ──────────────────────


def test_contract_resolver_preserves_all_preprocessing_fields():
    """Verify resolve() preserves every field in preprocessing_json without dropping any."""
    conn = MagicMock()
    custom_preprocessing = {
        "resize": [32, 32],
        "interpolation": "bilinear",
        "crop": {"size": [28, 28], "mode": "center"},
        "normalization": {"mean": [0.123, 0.456, 0.789], "std": [0.111, 0.222, 0.333]},
        "custom_transform_pipeline": ["random_horizontal_flip", "color_jitter"],
    }
    mock_build = {
        "dataset_build_id": "custom-build-1",
        "dataset_id": "ds-custom",
        "state": "READY",
        "dataset_manifest_hash": "a" * 64,
        "batch_size": 64,
        "shard_count": 3,
        "input_shape_json": [3, 32, 32],
        "dtype": "float32",
        "num_classes": 10,
        "preprocessing_json": custom_preprocessing,
    }

    req = {
        "dataset_build_id": "custom-build-1",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 5,
        "learning_rate": 0.01,
        "training_seed": 100,
    }

    with (
        patch(
            "pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build",
            return_value=mock_build,
        ),
        patch(
            "pbl4.management_backend.services.contract_resolver._get_task_type",
            return_value="image_classification",
        ),
    ):
        resolved = resolve(conn, req)

    # 1. Ensure all fields from custom_preprocessing are intact
    assert resolved["dataset"]["preprocessing"] == custom_preprocessing
    assert "resize" in resolved["dataset"]["preprocessing"]
    assert "crop" in resolved["dataset"]["preprocessing"]
    assert "custom_transform_pipeline" in resolved["dataset"]["preprocessing"]

    # 2. Ensure normalization was NOT overwritten by CIFAR-10 defaults
    norm = resolved["dataset"]["preprocessing"]["normalization"]
    assert norm["mean"] == [0.123, 0.456, 0.789]
    assert norm["std"] == [0.111, 0.222, 0.333]


def test_contract_resolver_does_not_invent_normalization_when_missing():
    """Verify resolve() does NOT inject CIFAR-10 mean/std when normalization is absent."""
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "mnist-build-1",
        "dataset_id": "ds-mnist",
        "state": "READY",
        "dataset_manifest_hash": "b" * 64,
        "batch_size": 32,
        "shard_count": 3,
        "input_shape_json": [1, 28, 28],
        "dtype": "float32",
        "num_classes": 10,
        "preprocessing_json": {
            "resize": [28, 28],
            "grayscale": True,
        },
    }

    req = {
        "dataset_build_id": "mnist-build-1",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 5,
        "learning_rate": 0.01,
        "training_seed": 100,
    }

    with (
        patch(
            "pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build",
            return_value=mock_build,
        ),
        patch(
            "pbl4.management_backend.services.contract_resolver._get_task_type",
            return_value="image_classification",
        ),
    ):
        resolved = resolve(conn, req)

    # Preprocessing must NOT contain fake CIFAR-10 normalization
    assert "normalization" not in resolved["dataset"]["preprocessing"]
    assert resolved["dataset"]["preprocessing"] == {
        "resize": [28, 28],
        "grayscale": True,
    }


def test_contract_resolver_fallback_to_manifest_snapshot():
    """Verify fallback to manifest_snapshot_jsonb if preprocessing_json is empty."""
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "snap-build-1",
        "dataset_id": "ds-snap",
        "state": "READY",
        "dataset_manifest_hash": "c" * 64,
        "batch_size": 64,
        "shard_count": 3,
        "input_shape_json": [3, 32, 32],
        "dtype": "float32",
        "num_classes": 10,
        "preprocessing_json": {},
        "manifest_snapshot_jsonb": {
            "preprocessing": {
                "auto_augmented": True,
                "pad": 4,
            }
        },
    }

    req = {
        "dataset_build_id": "snap-build-1",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 1,
        "learning_rate": 0.1,
        "training_seed": 42,
    }

    with (
        patch(
            "pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build",
            return_value=mock_build,
        ),
        patch(
            "pbl4.management_backend.services.contract_resolver._get_task_type",
            return_value="image_classification",
        ),
    ):
        resolved = resolve(conn, req)

    assert resolved["dataset"]["preprocessing"] == {
        "auto_augmented": True,
        "pad": 4,
    }


# ─── API POST /api/v1/jobs/{job_id}/validate Test ───────────────────────────


def test_api_validate_job_preserves_custom_preprocessing(app_client):
    """Verify POST /api/v1/jobs/{job_id}/validate returns full preprocessing in preview."""
    custom_preprocessing = {
        "target_resolution": [64, 64],
        "color_space": "RGB",
        "custom_normalize": {"scale": 255.0},
    }

    mock_validate_result = {
        "requested_contract": {
            "dataset_build_id": "dsb_custom",
            "model_id": "resnet18_groupnorm",
            "training_strategy": "strict_bsp",
            "epochs": 5,
            "learning_rate": 0.01,
            "training_seed": 42,
        },
        "resolved_preview": {
            "dataset": {
                "dataset_build_id": "dsb_custom",
                "dataset_manifest_hash": "d" * 64,
                "task_type": "image_classification",
                "input_shape": [3, 64, 64],
                "dtype": "float32",
                "num_classes": 10,
                "batch_size": 32,
                "shard_count": 3,
                "preprocessing": custom_preprocessing,
            },
            "model": {
                "model_id": "resnet18_groupnorm",
                "profile": "RESNET18_GROUPNORM_V1",
                "parameter_manifest_hash": "e" * 64,
            },
            "training": {
                "epochs": 5,
                "learning_rate": 0.01,
                "training_seed": 42,
            },
            "synchronization": {
                "training_strategy": "strict_bsp",
                "expected_workers": 3,
            },
            "update_policy": {"type": "plain_sgd_without_momentum"},
            "checkpoint_policy": {"type": "after_each_model_update_blocking", "schema_version": 1},
            "protocols": {"dtp_version": 1, "mcp_version": 1},
        },
        "warnings": [],
        "errors": [],
    }

    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch(
            "pbl4.management_backend.services.job_service.validate_job",
            return_value=mock_validate_result,
        ),
    ):
        res = app_client.post("/api/v1/jobs/job_test/validate")
        assert res.status_code == 200
        data = res.json()["data"]
        resolved_preview = data["resolved_preview"]
        assert resolved_preview is not None
        assert resolved_preview["dataset"]["preprocessing"] == custom_preprocessing


# ─── Regression Tests: Malformed Contract Fields ──────────────────────────────


def test_contract_resolver_malformed_input_shape_json_raises():
    """Verify resolve() raises ContractResolutionError when input_shape_json is malformed JSON."""
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "bad-shape-build",
        "dataset_id": "ds-bad-shape",
        "state": "READY",
        "dataset_manifest_hash": "a" * 64,
        "batch_size": 32,
        "shard_count": 3,
        "input_shape_json": "{not valid json",
        "dtype": "float32",
        "num_classes": 10,
        "preprocessing_json": {},
    }
    req = {
        "dataset_build_id": "bad-shape-build",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 1,
        "learning_rate": 0.01,
        "training_seed": 42,
    }

    with (
        patch(
            "pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build",
            return_value=mock_build,
        ),
        patch(
            "pbl4.management_backend.services.contract_resolver._get_task_type",
            return_value="image_classification",
        ),
        pytest.raises(ContractResolutionError, match="Malformed input_shape_json"),
    ):
        resolve(conn, req)


def test_contract_resolver_non_list_input_shape_json_raises():
    """Verify resolve() raises ContractResolutionError when input_shape_json is not a list."""
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "bad-shape-build-2",
        "dataset_id": "ds-bad-shape",
        "state": "READY",
        "dataset_manifest_hash": "a" * 64,
        "batch_size": 32,
        "shard_count": 3,
        "input_shape_json": '{"not": "a list"}',
        "dtype": "float32",
        "num_classes": 10,
        "preprocessing_json": {},
    }
    req = {
        "dataset_build_id": "bad-shape-build-2",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 1,
        "learning_rate": 0.01,
        "training_seed": 42,
    }

    with (
        patch(
            "pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build",
            return_value=mock_build,
        ),
        patch(
            "pbl4.management_backend.services.contract_resolver._get_task_type",
            return_value="image_classification",
        ),
        pytest.raises(ContractResolutionError, match="must decode to a list"),
    ):
        resolve(conn, req)


def test_contract_resolver_malformed_preprocessing_json_raises():
    """Verify resolve() raises ContractResolutionError when preprocessing_json is malformed JSON."""
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "bad-preproc-build",
        "dataset_id": "ds-bad-preproc",
        "state": "READY",
        "dataset_manifest_hash": "b" * 64,
        "batch_size": 32,
        "shard_count": 3,
        "input_shape_json": [3, 32, 32],
        "dtype": "float32",
        "num_classes": 10,
        "preprocessing_json": "{broken json: true",
    }
    req = {
        "dataset_build_id": "bad-preproc-build",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 1,
        "learning_rate": 0.01,
        "training_seed": 42,
    }

    with (
        patch(
            "pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build",
            return_value=mock_build,
        ),
        patch(
            "pbl4.management_backend.services.contract_resolver._get_task_type",
            return_value="image_classification",
        ),
        pytest.raises(ContractResolutionError, match="Malformed preprocessing_json"),
    ):
        resolve(conn, req)


def test_contract_resolver_non_dict_preprocessing_json_raises():
    """Verify resolve() raises ContractResolutionError when preprocessing_json is not a dict."""
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "bad-preproc-build-2",
        "dataset_id": "ds-bad-preproc",
        "state": "READY",
        "dataset_manifest_hash": "b" * 64,
        "batch_size": 32,
        "shard_count": 3,
        "input_shape_json": [3, 32, 32],
        "dtype": "float32",
        "num_classes": 10,
        "preprocessing_json": '["not", "a", "dict"]',
    }
    req = {
        "dataset_build_id": "bad-preproc-build-2",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 1,
        "learning_rate": 0.01,
        "training_seed": 42,
    }

    with (
        patch(
            "pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build",
            return_value=mock_build,
        ),
        patch(
            "pbl4.management_backend.services.contract_resolver._get_task_type",
            return_value="image_classification",
        ),
        pytest.raises(ContractResolutionError, match="must decode to an object/dict"),
    ):
        resolve(conn, req)
