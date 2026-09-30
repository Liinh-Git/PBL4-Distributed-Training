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
from pbl4.management_backend.services import job_service
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


@pytest.mark.parametrize(
    ("policy", "k", "expected_k"),
    [("equal", None, 3), ("dbs", 6, 6)],
)
def test_job_create_validate_freeze_workload_contract(policy, k, expected_k):
    conn = MagicMock()
    requested = {
        "dataset_build_id": "cifar10-v1-build",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 10,
        "learning_rate": 0.01,
        "training_seed": 42,
        "workload_policy": policy,
    }
    if k is not None:
        requested["work_units_per_step"] = k
    draft = {"job_id": "job-workload", "state": "DRAFT", "requested_contract": requested}
    build = {
        "dataset_build_id": "cifar10-v1-build",
        "dataset_id": "ds-cifar10",
        "state": "READY",
        "dataset_manifest_hash": "abc123hash",
        "batch_size": 128,
        "shard_count": 3,
    }
    with (
        patch("pbl4.management_backend.services.job_service.job_repository.create_job", return_value=draft),
        patch("pbl4.management_backend.services.job_service.job_repository.get_job", return_value=draft),
        patch("pbl4.management_backend.services.job_service.job_repository.freeze_job", return_value={"state": "READY"}) as freeze,
        patch("pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build", return_value=build),
        patch("pbl4.management_backend.services.contract_resolver._get_task_type", return_value="image_classification"),
    ):
        assert job_service.create_job(conn, display_name="Workload", description="", requested_contract=requested) == draft
        validation = job_service.validate_job(conn, "job-workload")
        assert validation["errors"] == []
        assert validation["resolved_preview"]["workload"]["work_units_per_step"] == expected_k
        assert job_service.freeze_job(conn, "job-workload")["state"] == "READY"
        assert freeze.call_args.kwargs["resolved_contract"]["workload"]["policy"] == policy


@pytest.mark.parametrize("k", [None, 3, 0])
def test_dbs_invalid_k_cannot_validate_or_freeze(k):
    requested = {
        "dataset_build_id": "cifar10-v1-build",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 10,
        "learning_rate": 0.01,
        "training_seed": 42,
        "workload_policy": "dbs",
    }
    if k is not None:
        requested["work_units_per_step"] = k
    draft = {"job_id": "job-invalid", "state": "DRAFT", "requested_contract": requested}
    with (
        patch("pbl4.management_backend.services.job_service.job_repository.get_job", return_value=draft),
        patch("pbl4.management_backend.services.job_service.job_repository.freeze_job") as freeze,
        patch("pbl4.management_backend.services.contract_resolver.dataset_build_repository.get_build", return_value={"dataset_build_id": "cifar10-v1-build", "dataset_id": "ds-cifar10", "state": "READY", "dataset_manifest_hash": "abc123hash", "batch_size": 128, "shard_count": 3}),
        patch("pbl4.management_backend.services.contract_resolver._get_task_type", return_value="image_classification"),
    ):
        assert job_service.validate_job(MagicMock(), "job-invalid")["errors"]
        with pytest.raises(job_service.JobValidationError):
            job_service.freeze_job(MagicMock(), "job-invalid")
        freeze.assert_not_called()


@pytest.mark.parametrize(
    ("old_policy", "old_k", "patch_contract", "expected_k"),
    [
        ("dbs", 8, {"workload_policy": "equal"}, None),
        ("equal", 4, {"workload_policy": "dbs"}, None),
        ("dbs", 8, {"epochs": 20}, 8),
        ("equal", 4, {"workload_policy": "dbs", "work_units_per_step": 6}, 6),
        ("dbs", 8, {"work_units_per_step": None}, None),
    ],
)
def test_draft_policy_change_does_not_carry_stale_k(old_policy, old_k, patch_contract, expected_k):
    requested = {
        "dataset_build_id": "build",
        "model_id": "resnet18_groupnorm",
        "training_strategy": "strict_bsp",
        "epochs": 10,
        "learning_rate": 0.01,
        "training_seed": 42,
        "workload_policy": old_policy,
        "work_units_per_step": old_k,
    }
    draft = {"job_id": "job-switch", "state": "DRAFT", "requested_contract": requested}

    def save(_conn, _job_id, **fields):
        return {**draft, "requested_contract": fields["requested_contract"]}

    with (
        patch("pbl4.management_backend.services.job_service.job_repository.get_job", return_value=draft),
        patch("pbl4.management_backend.services.job_service.job_repository.update_job", side_effect=save),
    ):
        updated = job_service.update_job(MagicMock(), "job-switch", requested_contract=patch_contract)
    merged = updated["requested_contract"]
    assert merged["workload_policy"] == patch_contract.get("workload_policy", old_policy)
    assert merged.get("work_units_per_step") == expected_k


def test_ready_job_policy_and_k_remain_frozen():
    ready = {"job_id": "job-frozen", "state": "READY", "requested_contract": {"workload_policy": "dbs", "work_units_per_step": 8}}
    with patch("pbl4.management_backend.services.job_service.job_repository.get_job", return_value=ready):
        with pytest.raises(job_service.JobFrozenError):
            job_service.update_job(MagicMock(), "job-frozen", requested_contract={"workload_policy": "equal"})


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
