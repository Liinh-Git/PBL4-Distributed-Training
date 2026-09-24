"""Unit tests for multi-Work-Unit TrainingLoop execution
and FP64 gradient accumulation (Task T4.2).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pbl4.adapter.models.resnet18_gn import build_resnet18_groupnorm
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.common.work_unit import WorkUnitRef
from pbl4.worker.dataset_cache import DatasetCache
from pbl4.worker.shard_cache import CachedShard, ShardCache, ShardCacheKey
from pbl4.worker.training_loop import StepAssignment, TrainingLoop
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts


@pytest.fixture
def multi_shard_setup(tmp_path: Path):
    dest = tmp_path / "artifacts"
    artifacts = create_synthetic_dataset_artifacts(
        destination_dir=dest,
        dataset_build_id="build-multi-unit-test",
        shard_count=2,
        batches_per_shard=2,
        batch_size=4,
        input_shape=(3, 2, 2),
    )
    cache = ShardCache(tmp_path / "cache")
    cached_shards: dict[int, CachedShard] = {}
    for s_id in range(2):
        key = ShardCacheKey(
            artifacts.dataset_build_id, artifacts.dataset_manifest_hash, shard_id=s_id
        )
        cached = cache.publish(
            key,
            artifacts.root_manifest_bytes,
            artifacts.shard_manifest_bytes[s_id],
            artifacts.shard_batch_bytes[s_id],
        )
        cached_shards[s_id] = cached

    dataset_cache = DatasetCache(
        artifacts.dataset_build_id, artifacts.dataset_manifest_hash, cached_shards
    )
    return artifacts, cached_shards, dataset_cache


def create_adapter(seed: int = 42) -> PyTorchAdapter:
    from torch.nn import functional

    model = build_resnet18_groupnorm(initialization_seed=seed, device="cpu")
    return PyTorchAdapter(model, functional.cross_entropy, local_gradient_reduction="mean")


def test_single_unit_matches_adapter_direct_call(multi_shard_setup):
    _, _, dataset_cache = multi_shard_setup
    adapter = create_adapter(seed=123)
    loop = TrainingLoop(adapter, dataset_cache, model_version=0)

    unit = WorkUnitRef(shard_id=0, batch_id=0, sample_count=4)
    step = StepAssignment(
        attempt_id="att-1",
        session_id=1,
        worker_id=0,
        operation_id=1,
        step_id=0,
        input_model_version=0,
        batch_ordinal=0,
        work_units=(unit,),
        expected_sample_count=4,
    )

    # Compute through loop
    computed = loop.compute(step)
    grad = computed.local_gradient

    # Compute directly on data with fresh adapter with same weights
    adapter_direct = create_adapter(seed=123)
    x, y, _ = dataset_cache.load_work_unit(unit)
    direct_grad = adapter_direct.compute_loss_and_gradients(x, y)

    assert grad.sample_count == 4
    assert np.isclose(grad.loss, direct_grad.loss, rtol=1e-5)
    for t_loop, t_dir in zip(grad.bundle.tensors, direct_grad.bundle.tensors, strict=True):
        np.testing.assert_allclose(t_loop, t_dir, rtol=1e-5, atol=1e-6)


def test_multi_unit_produces_exact_sample_weighted_average(multi_shard_setup):
    _, _, dataset_cache = multi_shard_setup

    u1 = WorkUnitRef(shard_id=0, batch_id=0, sample_count=4)
    u2 = WorkUnitRef(shard_id=0, batch_id=1, sample_count=4)

    # Run separate direct adapter calls to get individual gradients
    adapter1 = create_adapter(seed=999)
    x1, y1, _ = dataset_cache.load_work_unit(u1)
    g1 = adapter1.compute_loss_and_gradients(x1, y1)

    adapter2 = create_adapter(seed=999)
    x2, y2, _ = dataset_cache.load_work_unit(u2)
    g2 = adapter2.compute_loss_and_gradients(x2, y2)

    # Expected weighted mean
    expected_loss = (g1.loss * 4 + g2.loss * 4) / 8.0
    expected_tensors = [
        ((t1.astype(np.float64) * 4 + t2.astype(np.float64) * 4) / 8.0).astype(np.float32)
        for t1, t2 in zip(g1.bundle.tensors, g2.bundle.tensors, strict=True)
    ]

    # Run multi-unit TrainingLoop
    loop_adapter = create_adapter(seed=999)
    loop = TrainingLoop(loop_adapter, dataset_cache, model_version=0)
    step = StepAssignment(
        attempt_id="att-1",
        session_id=1,
        worker_id=0,
        operation_id=1,
        step_id=0,
        input_model_version=0,
        batch_ordinal=0,
        work_units=(u1, u2),
        expected_sample_count=8,
    )

    computed = loop.compute(step)
    multi_grad = computed.local_gradient

    assert multi_grad.sample_count == 8
    assert np.isclose(multi_grad.loss, expected_loss, rtol=1e-5)
    for t_act, t_exp in zip(multi_grad.bundle.tensors, expected_tensors, strict=True):
        np.testing.assert_allclose(t_act, t_exp, rtol=1e-5, atol=1e-6)


def test_multi_unit_across_different_shards(multi_shard_setup):
    _, _, dataset_cache = multi_shard_setup
    adapter = create_adapter(seed=555)
    loop = TrainingLoop(adapter, dataset_cache, model_version=0)

    # One unit on shard 0, one unit on shard 1
    u_s0 = WorkUnitRef(shard_id=0, batch_id=0, sample_count=4)
    u_s1 = WorkUnitRef(shard_id=1, batch_id=1, sample_count=4)

    step = StepAssignment(
        attempt_id="att-1",
        session_id=1,
        worker_id=0,
        operation_id=1,
        step_id=0,
        input_model_version=0,
        batch_ordinal=0,
        work_units=(u_s0, u_s1),
        expected_sample_count=8,
    )

    computed = loop.compute(step)
    assert computed.local_gradient.sample_count == 8
    assert computed.assignment.shard_id == 0
    assert computed.assignment.batch_id == 0


def test_apply_parameters_and_eligibility_flow(multi_shard_setup):
    _, _, dataset_cache = multi_shard_setup
    adapter = create_adapter(seed=42)
    loop = TrainingLoop(adapter, dataset_cache, model_version=0)

    u = WorkUnitRef(shard_id=0, batch_id=0, sample_count=4)
    step = StepAssignment(
        attempt_id="att-1",
        session_id=1,
        worker_id=0,
        operation_id=1,
        step_id=0,
        input_model_version=0,
        batch_ordinal=0,
        work_units=(u,),
        expected_sample_count=4,
    )

    loop.compute(step)
    assert loop.local_model_version == 0

    # Cannot compute while pending parameter application
    with pytest.raises(ValueError, match="Previous operation awaits canonical parameters"):
        loop.compute(step)

    # Cannot consume before application
    with pytest.raises(ValueError, match="not ACK-eligible"):
        loop.consume_parameter_applied()

    # Apply new parameters
    new_bundle = adapter.export_parameters()
    eligibility = loop.apply_parameters(step, target_model_version=1, bundle=new_bundle)
    assert eligibility.model_version == 1
    assert loop.local_model_version == 1

    # Consume eligibility
    consumed = loop.consume_parameter_applied()
    assert consumed == eligibility

    # Subsequent consume raises
    with pytest.raises(ValueError, match="not ACK-eligible"):
        loop.consume_parameter_applied()


def test_validation_errors(multi_shard_setup):
    _, _, dataset_cache = multi_shard_setup
    adapter = create_adapter(seed=42)
    loop = TrainingLoop(adapter, dataset_cache, model_version=0)

    u_missing = WorkUnitRef(shard_id=99, batch_id=0, sample_count=4)
    step_missing_shard = StepAssignment(
        attempt_id="att-1",
        session_id=1,
        worker_id=0,
        operation_id=1,
        step_id=0,
        input_model_version=0,
        batch_ordinal=0,
        work_units=(u_missing,),
        expected_sample_count=4,
    )
    with pytest.raises(ValueError, match="shard assignment 99 does not match"):
        loop.compute(step_missing_shard)

    u_valid = WorkUnitRef(shard_id=0, batch_id=0, sample_count=4)
    step_wrong_version = StepAssignment(
        attempt_id="att-1",
        session_id=1,
        worker_id=0,
        operation_id=1,
        step_id=0,
        input_model_version=5,  # loop is at 0
        batch_ordinal=0,
        work_units=(u_valid,),
        expected_sample_count=4,
    )
    with pytest.raises(ValueError, match="wrong local model version"):
        loop.compute(step_wrong_version)
