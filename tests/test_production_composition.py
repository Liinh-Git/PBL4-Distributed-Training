from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from pbl4.adapter.models.resnet18_gn import build_resnet18_groupnorm
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.runtime.batch_scheduler import RecoveryCursor
from pbl4.runtime.canonical_model import ModelSnapshot
from pbl4.runtime.checkpoint_v1 import CheckpointV1Serializer
from pbl4.runtime.snapshot import CheckpointSnapshot


def test_real_resnet18_groupnorm_has_stable_parameter_manifest():
    from torch.nn import GroupNorm, functional

    first = PyTorchAdapter(
        build_resnet18_groupnorm(initialization_seed=123, device="cpu"),
        functional.cross_entropy,
        local_gradient_reduction="mean",
    )
    second = PyTorchAdapter(
        build_resnet18_groupnorm(initialization_seed=456, device="cpu"),
        functional.cross_entropy,
        local_gradient_reduction="mean",
    )
    assert first.manifest == second.manifest
    assert first.manifest.total_numel == 11_173_962
    assert first.manifest.total_bytes == 44_695_848
    groups = [module for module in first._model.modules() if isinstance(module, GroupNorm)]
    assert groups and all(module.num_groups <= 32 for module in groups)
    assert first._model.conv1.kernel_size == (3, 3)
    assert first._model.conv1.stride == (1, 1)


def _snapshot() -> CheckpointSnapshot:
    return CheckpointSnapshot(
        checkpoint_id="checkpoint-1",
        checkpoint_schema_version=1,
        job_id="job-1",
        created_by_attempt_id="attempt-1",
        contract_hash="a" * 64,
        checkpoint_policy="after_each_model_update_blocking",
        checkpoint_policy_version=1,
        training_strategy="strict_bsp",
        dataset_build_id="build-1",
        dataset_manifest_hash="b" * 64,
        model_id="resnet18_groupnorm",
        model_profile="RESNET18_GROUPNORM_V1",
        source_operation_id=3,
        source_step_id=3,
        optimizer="plain_sgd_without_momentum",
        created_at="2026-09-10T00:00:00+00:00",
        model=ModelSnapshot(4, "c" * 64, np.arange(8, dtype=np.float32).tobytes()),
        recovery_cursor=RecoveryCursor(0, 4),
    )


def test_checkpoint_v1_round_trip_and_integrity_rejection():
    serializer = CheckpointV1Serializer()
    expected = _snapshot()
    payload, metadata = serializer.serialize(expected)
    assert serializer.deserialize(payload, metadata) == expected
    tampered = bytearray(payload)
    tampered[0] ^= 1
    with pytest.raises(ValueError, match="integrity"):
        serializer.deserialize(bytes(tampered), metadata)
    with pytest.raises(ValueError, match="canonical"):
        serializer.deserialize(payload, metadata + b"\n")
    with pytest.raises(ValueError, match="manifest hash"):
        serializer.serialize(replace(expected, model=ModelSnapshot(4, "bad", payload)))
