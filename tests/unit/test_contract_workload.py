"""Unit tests for workload policy and work_units_per_step in Job contracts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from pbl4.common.hashing import canonical_json_hash
from pbl4.management_backend.schemas.job import (
    RequestedContractPatchV1,
    RequestedContractV1,
    ResolvedContractV1,
)
from pbl4.management_backend.services.contract_resolver import (
    ContractResolutionError,
    hash_contract,
    resolve,
)
from pbl4.management_backend.services.model_catalog import (
    FakeModelMetadataProvider,
    get_model_metadata_provider,
    set_model_metadata_provider,
)


@pytest.fixture(autouse=True)
def setup_fake_model_metadata():
    orig = get_model_metadata_provider()
    set_model_metadata_provider(FakeModelMetadataProvider())
    yield
    set_model_metadata_provider(orig)


def test_requested_contract_workload_defaults():
    req = RequestedContractV1(
        dataset_build_id="build-1",
        model_id="resnet18_groupnorm",
        epochs=5,
        learning_rate=0.01,
        training_seed=42,
    )
    assert req.workload_policy == "equal"
    assert req.work_units_per_step is None


def test_requested_contract_workload_valid_dbs():
    req = RequestedContractV1(
        dataset_build_id="build-1",
        model_id="resnet18_groupnorm",
        epochs=5,
        learning_rate=0.01,
        training_seed=42,
        workload_policy="dbs",
        work_units_per_step=12,
    )
    assert req.workload_policy == "dbs"
    assert req.work_units_per_step == 12


def test_requested_contract_rejects_bool_work_units_per_step():
    with pytest.raises(ValidationError):
        RequestedContractV1(
            dataset_build_id="build-1",
            model_id="resnet18_groupnorm",
            epochs=5,
            learning_rate=0.01,
            training_seed=42,
            work_units_per_step=True,  # type: ignore
        )


def test_requested_contract_rejects_invalid_workload_policy():
    with pytest.raises(ValidationError):
        RequestedContractV1(
            dataset_build_id="build-1",
            model_id="resnet18_groupnorm",
            epochs=5,
            learning_rate=0.01,
            training_seed=42,
            workload_policy="dbs_bsp",
        )


def test_requested_contract_patch_validation():
    patch_req = RequestedContractPatchV1(
        workload_policy="dbs",
        work_units_per_step=6,
    )
    assert patch_req.workload_policy == "dbs"
    assert patch_req.work_units_per_step == 6

    with pytest.raises(ValidationError):
        RequestedContractPatchV1(workload_policy="invalid_policy")

    with pytest.raises(ValidationError):
        RequestedContractPatchV1(work_units_per_step=False)  # type: ignore


def test_contract_resolver_equal_policy_default_k():
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "cifar10-v1-build",
        "dataset_id": "ds-cifar10",
        "state": "READY",
        "dataset_manifest_hash": "abc123hash",
        "batch_size": 128,
        "shard_count": 3,
        "metadata_jsonb": {"total_samples": 50000},
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
            "workload_policy": "equal",
        }
        resolved = resolve(conn, req)
        assert resolved["workload"]["policy"] == "equal"
        assert resolved["workload"]["work_units_per_step"] == 3


def test_contract_resolver_equal_policy_custom_k():
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "cifar10-v1-build",
        "dataset_id": "ds-cifar10",
        "state": "READY",
        "dataset_manifest_hash": "abc123hash",
        "batch_size": 128,
        "shard_count": 3,
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
        # K >= expected_workers succeeds
        req = {
            "dataset_build_id": "cifar10-v1-build",
            "model_id": "resnet18_groupnorm",
            "epochs": 10,
            "learning_rate": 0.01,
            "training_seed": 42,
            "workload_policy": "equal",
            "work_units_per_step": 6,
        }
        resolved = resolve(conn, req)
        assert resolved["workload"]["work_units_per_step"] == 6

        # K < expected_workers fails
        req_invalid = dict(req, work_units_per_step=2)
        with pytest.raises(ContractResolutionError) as exc_info:
            resolve(conn, req_invalid)
        assert any("must be >= expected_workers" in err for err in exc_info.value.errors)


def test_contract_resolver_dbs_policy_requires_k_greater_than_expected_workers():
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "cifar10-v1-build",
        "dataset_id": "ds-cifar10",
        "state": "READY",
        "dataset_manifest_hash": "abc123hash",
        "batch_size": 128,
        "shard_count": 3,
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
        # Missing work_units_per_step
        with pytest.raises(ContractResolutionError) as exc_info:
            resolve(
                conn,
                {
                    "dataset_build_id": "cifar10-v1-build",
                    "model_id": "resnet18_groupnorm",
                    "epochs": 10,
                    "learning_rate": 0.01,
                    "training_seed": 42,
                    "workload_policy": "dbs",
                },
            )
        assert any("work_units_per_step is required" in err for err in exc_info.value.errors)

        # K == expected_workers (3) fails for DBS
        with pytest.raises(ContractResolutionError) as exc_info:
            resolve(
                conn,
                {
                    "dataset_build_id": "cifar10-v1-build",
                    "model_id": "resnet18_groupnorm",
                    "epochs": 10,
                    "learning_rate": 0.01,
                    "training_seed": 42,
                    "workload_policy": "dbs",
                    "work_units_per_step": 3,
                },
            )
        assert any("strictly greater than expected_workers" in err for err in exc_info.value.errors)

        # K > expected_workers succeeds
        resolved = resolve(
            conn,
            {
                "dataset_build_id": "cifar10-v1-build",
                "model_id": "resnet18_groupnorm",
                "epochs": 10,
                "learning_rate": 0.01,
                "training_seed": 42,
                "workload_policy": "dbs",
                "work_units_per_step": 12,
            },
        )
        assert resolved["workload"]["policy"] == "dbs"
        assert resolved["workload"]["work_units_per_step"] == 12


def test_contract_resolver_rejects_non_positive_batch_size():
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "cifar10-v1-build",
        "dataset_id": "ds-cifar10",
        "state": "READY",
        "dataset_manifest_hash": "abc123hash",
        "batch_size": 0,
        "shard_count": 3,
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
        with pytest.raises(ContractResolutionError) as exc_info:
            resolve(
                conn,
                {
                    "dataset_build_id": "cifar10-v1-build",
                    "model_id": "resnet18_groupnorm",
                    "epochs": 10,
                    "learning_rate": 0.01,
                    "training_seed": 42,
                },
            )
        assert any(
            "must have a positive integer batch_size" in err for err in exc_info.value.errors
        )


def test_resolved_contract_v1_pydantic_roundtrip():
    conn = MagicMock()
    mock_build = {
        "dataset_build_id": "cifar10-v1-build",
        "dataset_id": "ds-cifar10",
        "state": "READY",
        "dataset_manifest_hash": "abc123hash",
        "batch_size": 128,
        "shard_count": 3,
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
        resolved_dict = resolve(
            conn,
            {
                "dataset_build_id": "cifar10-v1-build",
                "model_id": "resnet18_groupnorm",
                "epochs": 10,
                "learning_rate": 0.01,
                "training_seed": 42,
                "workload_policy": "dbs",
                "work_units_per_step": 9,
            },
        )
        parsed = ResolvedContractV1.model_validate(resolved_dict)
        assert parsed.workload.policy == "dbs"
        assert parsed.workload.work_units_per_step == 9

        # Contract hash includes workload
        h = hash_contract(resolved_dict)
        assert len(h) == 64
        assert h == canonical_json_hash(resolved_dict)
