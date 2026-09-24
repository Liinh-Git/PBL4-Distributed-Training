"""Tests for contract resolution, model catalog, and canonical hashing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pbl4.common.hashing import canonical_json_dumps, canonical_json_hash
from pbl4.management_backend.services.contract_resolver import (
    ContractResolutionError,
    resolve,
)
from pbl4.management_backend.services.model_catalog import (
    FakeModelMetadataProvider,
    get_model_metadata_provider,
    get_model_spec,
    is_supported_model,
    list_supported_models,
    set_model_metadata_provider,
)


@pytest.fixture(autouse=True)
def setup_fake_model_metadata():
    orig = get_model_metadata_provider()
    set_model_metadata_provider(FakeModelMetadataProvider())
    yield
    set_model_metadata_provider(orig)


def test_model_catalog_v1_resnet18_groupnorm():
    assert is_supported_model("resnet18_groupnorm") is True
    assert is_supported_model("RESNET18_GROUPNORM_V1") is True
    assert is_supported_model("resnet50") is False

    spec = get_model_spec("resnet18_groupnorm")
    assert spec is not None
    assert spec["model_id"] == "resnet18_groupnorm"
    assert spec["num_classes"] == 10
    assert spec["profile"] == "RESNET18_GROUPNORM_V1"

    models = list_supported_models()
    assert len(models) == 1
    assert models[0]["model_id"] == "resnet18_groupnorm"


def test_canonical_json_hashing_determinism():
    dict1 = {"b": 2, "a": 1, "nested": {"z": 10, "y": 20}}
    dict2 = {"nested": {"y": 20, "z": 10}, "a": 1, "b": 2}

    json1 = canonical_json_dumps(dict1)
    json2 = canonical_json_dumps(dict2)
    assert json1 == json2

    hash1 = canonical_json_hash(dict1)
    hash2 = canonical_json_hash(dict2)
    assert hash1 == hash2
    assert len(hash1) == 64


def test_contract_resolver_success():
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "cifar10-v1-build",
        "dataset_id": "ds-cifar10",
        "state": "READY",
        "dataset_manifest_hash": "abc123hash",
        "batch_size": 128,
        "shard_count": 3,
        "metadata_jsonb": {"total_samples": 50000, "splits": {"train": 50000}},
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
        req = {
            "dataset_build_id": "cifar10-v1-build",
            "model_id": "resnet18_groupnorm",
            "training_strategy": "strict_bsp",
            "epochs": 10,
            "learning_rate": 0.01,
            "training_seed": 42,
        }

        resolved = resolve(conn, req)
        assert resolved["model"]["model_id"] == "resnet18_groupnorm"
        assert resolved["synchronization"]["training_strategy"] == "strict_bsp"
        assert resolved["synchronization"]["expected_workers"] == 3
        assert resolved["update_policy"]["type"] == "plain_sgd_without_momentum"
        assert resolved["checkpoint_policy"]["type"] == "after_each_model_update_blocking"
        assert "cadence" not in resolved["checkpoint_policy"]
        assert resolved["checkpoint_policy"]["schema_version"] == 1


def test_contract_resolver_rejections():
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "cifar10-v1-build",
        "dataset_id": "ds-cifar10",
        "state": "READY",
        "dataset_manifest_hash": "abc123hash",
        "batch_size": 128,
        "shard_count": 3,
        "metadata_jsonb": {"total_samples": 50000, "splits": {"train": 50000}},
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
        # Unsupported model
        with pytest.raises(ContractResolutionError) as exc_info:
            resolve(
                conn,
                {
                    "dataset_build_id": "cifar10-v1-build",
                    "model_id": "vgg16",
                    "training_strategy": "strict_bsp",
                    "epochs": 5,
                },
            )
        assert any("Unsupported model_id" in err for err in exc_info.value.errors)

        # Unsupported strategy
        with pytest.raises(ContractResolutionError) as exc_info:
            resolve(
                conn,
                {
                    "dataset_build_id": "cifar10-v1-build",
                    "model_id": "resnet18_groupnorm",
                    "training_strategy": "asynchronous_parameter_server",
                    "epochs": 5,
                },
            )
        assert any("Unsupported training_strategy" in err for err in exc_info.value.errors)


# ─── WorkerSessionItem Strictness Tests ──────────────────────────────────────


def test_worker_session_item_schema_strictness():
    """Verify that WorkerSessionItem strictly requires protocol_version and connected_at.

    Neither field may be omitted or defaulted to prevent fabricating metadata or masking data corruption.
    """
    from datetime import UTC, datetime
    from pydantic import ValidationError
    from pbl4.management_backend.schemas.attempt import WorkerSessionItem

    now = datetime.now(UTC)

    # 1. Valid instantiation succeeds
    item = WorkerSessionItem(
        worker_id=0,
        session_id="101",
        node_label="worker-node-0",
        state="READY",
        protocol_version=1,
        connected_at=now,
    )
    assert item.worker_id == 0
    assert item.session_id == "101"
    assert item.protocol_version == 1
    assert item.connected_at == now

    # 2. Missing protocol_version must raise ValidationError (cannot silently default to 1)
    with pytest.raises(ValidationError) as exc_info:
        WorkerSessionItem(
            worker_id=0,
            session_id="101",
            node_label="worker-node-0",
            state="READY",
            connected_at=now,
        )
    assert "protocol_version" in str(exc_info.value)

    # 3. Missing connected_at must raise ValidationError (cannot silently default to None)
    with pytest.raises(ValidationError) as exc_info:
        WorkerSessionItem(
            worker_id=0,
            session_id="101",
            node_label="worker-node-0",
            state="READY",
            protocol_version=1,
        )
    assert "connected_at" in str(exc_info.value)

    # 4. connected_at=None must raise ValidationError
    with pytest.raises(ValidationError) as exc_info:
        WorkerSessionItem(
            worker_id=0,
            session_id="101",
            node_label="worker-node-0",
            state="READY",
            protocol_version=1,
            connected_at=None,
        )
    assert "connected_at" in str(exc_info.value)
