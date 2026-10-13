"""Regression coverage for the lightweight workload and real Agent dispatch."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from torch.nn import functional

from pbl4.adapter.models.factory import build_model
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.agent_protocol.messages import StartWorkerPayload
from pbl4.management_backend.services import attempt_service
from pbl4.management_backend.services.dataset_service import resolve_dataset_manager_source
from pbl4.management_backend.services.model_catalog import DefaultModelMetadataProvider, get_model


def test_small_model_reproducible_manifest_and_real_gradient():
    def adapter(seed):
        return PyTorchAdapter(
            build_model("small_cnn", initialization_seed=seed),
            functional.cross_entropy,
            local_gradient_reduction="mean",
        )

    left, same, other = adapter(42), adapter(42), adapter(43)
    assert left.manifest.total_numel < 1000
    assert left.manifest == same.manifest == other.manifest
    for a, b in zip(
        left.export_parameters().tensors, same.export_parameters().tensors, strict=True
    ):
        np.testing.assert_array_equal(a, b)
    assert any(
        not np.array_equal(a, b)
        for a, b in zip(
            left.export_parameters().tensors, other.export_parameters().tensors, strict=True
        )
    )
    gradient = left.compute_loss_and_gradients(
        np.ones((16, 3, 32, 32), dtype=np.float32), np.arange(16, dtype=np.int64) % 10
    )
    assert gradient.sample_count == 16 and np.isfinite(gradient.loss)
    assert any(np.any(tensor != 0) for tensor in gradient.bundle.tensors)
    assert get_model("resnet18_groupnorm")["profile"] == "RESNET18_GROUPNORM_V1"


def test_small_model_metadata_never_uses_resnet_global_hash(monkeypatch):
    monkeypatch.delenv("PARAMETER_MANIFEST_HASH_SMALL_CNN", raising=False)
    monkeypatch.setenv("CANONICAL_PARAMETER_MANIFEST_HASH", "a" * 64)
    provider = DefaultModelMetadataProvider()
    assert provider.get_model_metadata("small_cnn")["parameter_manifest_hash"] is None
    monkeypatch.setenv("PARAMETER_MANIFEST_HASH_SMALL_CNN", "b" * 64)
    assert provider.get_model_metadata("small_cnn")["parameter_manifest_hash"] == "b" * 64


def test_start_worker_model_extension_defaults_and_round_trip():
    command = StartWorkerPayload(
        "cmd",
        "alloc",
        "attempt",
        "localhost",
        9000,
        "cpu",
        42,
        "private-token",
        model_id="small_cnn",
    )
    assert StartWorkerPayload.from_dict(command.to_dict()).model_id == "small_cnn"
    legacy = command.to_dict()
    legacy.pop("model_id")
    assert StartWorkerPayload.from_dict(legacy).model_id == "resnet18_groupnorm"
    assert "private-token" not in repr(command)
    assert "private-token" not in str(command.to_dict(redact=True))


def test_synthetic_source_is_not_cifar():
    assert (
        resolve_dataset_manager_source("builtin", "synthetic_smoke_v1")["type"] == "synthetic_smoke"
    )
    assert resolve_dataset_manager_source("builtin", "cifar10")["type"] == "cifar10_download"


def test_resume_rejects_nested_dataset_mismatch_before_allocation():
    job = {
        "state": "READY",
        "contract_hash": "hash",
        "resolved_contract": {"dataset": {"dataset_build_id": "expected"}},
    }
    ckpt = {
        "state": "COMPLETE",
        "contract_hash": "hash",
        "dataset_build_id": "wrong",
        "created_by_attempt_id": "old",
        "model_sha256": "a" * 64,
        "metadata_sha256": "b" * 64,
    }
    with (
        patch.object(attempt_service.job_repository, "get_job", return_value=job),
        patch.object(attempt_service.checkpoint_repository, "get_checkpoint", return_value=ckpt),
        patch.object(attempt_service.attempt_repository, "get_active_attempt") as active,
    ):
        with pytest.raises(
            attempt_service.CheckpointContractMismatchError, match="dataset_build_id"
        ):
            attempt_service.resume_job(MagicMock(), "job", "checkpoint")
        active.assert_not_called()


@pytest.mark.parametrize("model_id", ["small_cnn", "resnet18_groupnorm"])
def test_model_rejects_incompatible_dataset(model_id, monkeypatch):
    from pbl4.management_backend.services import contract_resolver
    from pbl4.management_backend.services.model_catalog import FakeModelMetadataProvider

    monkeypatch.setattr(contract_resolver, "get_model_metadata_provider", FakeModelMetadataProvider)
    build = {
        "dataset_build_id": "build",
        "dataset_id": "dataset",
        "state": "READY",
        "dataset_manifest_hash": "a" * 64,
        "batch_size": 16,
        "shard_count": 3,
        "input_shape_json": [1, 28, 28],
        "num_classes": 10,
        "dtype": "float32",
    }
    with (
        patch.object(contract_resolver.dataset_build_repository, "get_build", return_value=build),
        patch.object(contract_resolver, "_get_task_type", return_value="image_classification"),
    ):
        with pytest.raises(contract_resolver.ContractResolutionError, match="incompatible"):
            contract_resolver.resolve(
                MagicMock(),
                {
                    "dataset_build_id": "build",
                    "model_id": model_id,
                    "epochs": 1,
                    "learning_rate": 0.01,
                    "training_seed": 42,
                },
            )
