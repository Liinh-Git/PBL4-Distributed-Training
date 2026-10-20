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
    assert {model["model_id"] for model in models} == {"resnet18_groupnorm", "small_cnn"}
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
        assert resolved["checkpoint_policy"]["type"] == "periodic"
        assert resolved["checkpoint_policy"]["policy_version"] == 1
        assert resolved["checkpoint_policy"]["schema_version"] == 1
        assert resolved["checkpoint_policy"]["every_n_epochs"] == 5


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

    Neither field may be omitted or defaulted to prevent fabricating metadata
    or masking data corruption.
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


# ─── B1 Checkpoint Cadence & Contract Tests ──────────────────────────────────


def test_contract_resolver_checkpoint_cadence_options():
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
        base_req = {
            "dataset_build_id": "cifar10-v1-build",
            "model_id": "resnet18_groupnorm",
            "training_strategy": "strict_bsp",
            "epochs": 10,
            "learning_rate": 0.01,
            "training_seed": 42,
        }

        # 1. Default N=5 when omitted
        res_default = resolve(conn, base_req)
        assert res_default["checkpoint_policy"]["every_n_epochs"] == 5

        # 2. Explicit N=1
        res_1 = resolve(conn, {**base_req, "checkpoint": {"every_n_epochs": 1}})
        assert res_1["checkpoint_policy"]["every_n_epochs"] == 1

        # 3. Explicit N=7
        res_7 = resolve(conn, {**base_req, "checkpoint": {"every_n_epochs": 7}})
        assert res_7["checkpoint_policy"]["every_n_epochs"] == 7

        # 4. Changing N changes contract hash
        hash_5 = canonical_json_hash(res_default)
        hash_1 = canonical_json_hash(res_1)
        hash_7 = canonical_json_hash(res_7)
        assert hash_5 != hash_1
        assert hash_5 != hash_7
        assert hash_1 != hash_7


def test_contract_resolver_checkpoint_strict_validation():
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
        base_req = {
            "dataset_build_id": "cifar10-v1-build",
            "model_id": "resnet18_groupnorm",
            "training_strategy": "strict_bsp",
            "epochs": 10,
            "learning_rate": 0.01,
            "training_seed": 42,
        }

        invalid_cases = [
            {"every_n_epochs": 0},
            {"every_n_epochs": -1},
            {"every_n_epochs": 5.0},
            {"every_n_epochs": "5"},
            {"every_n_epochs": True},
            {},
            {"every_n_epochs": 5, "extra_field": "invalid"},
        ]

        for invalid_cp in invalid_cases:
            with pytest.raises(ContractResolutionError):
                resolve(conn, {**base_req, "checkpoint": invalid_cp})

        # Reject legacy policy key
        with pytest.raises(ContractResolutionError):
            resolve(conn, {**base_req, "checkpoint_policy": "after_each_model_update_blocking"})


def test_job_service_checkpoint_preservation_and_legacy_rejection():
    from pbl4.management_backend.services import job_service

    conn = MagicMock()

    # 1. create_job defaults N=5 when omitted
    mock_row = {
        "job_id": "job_01",
        "state": "DRAFT",
        "requested_contract": {
            "dataset_build_id": "b1",
            "model_id": "m1",
            "epochs": 10,
            "learning_rate": 0.01,
            "training_seed": 42,
            "training_strategy": "strict_bsp",
            "checkpoint": {"every_n_epochs": 5},
        },
    }
    with patch("pbl4.management_backend.repositories.job_repository.create_job", return_value=mock_row):
        created = job_service.create_job(
            conn,
            display_name="Test Job",
            description="",
            requested_contract={
                "dataset_build_id": "b1",
                "model_id": "m1",
                "epochs": 10,
                "learning_rate": 0.01,
                "training_seed": 42,
                "training_strategy": "strict_bsp",
            },
        )
        assert created["requested_contract"]["checkpoint"]["every_n_epochs"] == 5

    # 2. update_job preserves N when patching unrelated field
    with (
        patch("pbl4.management_backend.repositories.job_repository.get_job", return_value=mock_row),
        patch("pbl4.management_backend.repositories.job_repository.update_job", return_value=mock_row) as mock_up,
    ):
        job_service.update_job(
            conn,
            "job_01",
            requested_contract={"epochs": 20},
        )
        called_rc = mock_up.call_args[1]["requested_contract"]
        assert called_rc["epochs"] == 20
        assert called_rc["checkpoint"]["every_n_epochs"] == 5

    # 3. update_job rejects checkpoint: None
    with patch("pbl4.management_backend.repositories.job_repository.get_job", return_value=mock_row):
        with pytest.raises(job_service.JobValidationError):
            job_service.update_job(
                conn,
                "job_01",
                requested_contract={"checkpoint": None},
            )

    # 4. clone_job rejects legacy job without checkpoint
    legacy_mock_row = {
        "job_id": "job_legacy",
        "state": "READY",
        "display_name": "Legacy Job",
        "requested_contract": {
            "dataset_build_id": "b1",
            "model_id": "m1",
            "epochs": 10,
            "learning_rate": 0.01,
            "training_seed": 42,
            "training_strategy": "strict_bsp",
        },
    }
    with patch("pbl4.management_backend.repositories.job_repository.get_job", return_value=legacy_mock_row):
        with pytest.raises(job_service.JobValidationError):
            job_service.clone_job(conn, "job_legacy")

