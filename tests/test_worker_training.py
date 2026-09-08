"""Worker-local assigned-batch, cache, version, application, and ACK tests."""

import json
from dataclasses import replace

import numpy as np
import pytest
import torch
from torch.nn import functional as functional

from pbl4.adapter.base import TensorBundle
from pbl4.adapter.models.small_cnn import SmallCNN
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.dataset_manager.config import DatasetBuildConfig
from pbl4.dataset_manager.preprocessing import Preprocessor
from pbl4.dataset_manager.storage import DatasetStorage
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.training_loop import StepAssignment, TrainingLoop
from pbl4.worker.worker_state import WorkerSessionState, WorkerState


def dataset_config(**changes) -> DatasetBuildConfig:
    base = DatasetBuildConfig(
        1,
        "build-worker-test",
        "cifar10",
        "CIFAR-10",
        "CNN_IMAGE_CLASSIFICATION_V1",
        "image_classification",
        (3, 2, 2),
        "float32",
        10,
        {
            "channel_order": "NCHW",
            "scale": "uint8_to_unit",
            "mean": [0.5, 0.5, 0.5],
            "std": [0.5, 0.5, 0.5],
        },
        2,
        2,
        "seeded_permutation_round_robin",
        42,
    )
    return replace(base, **changes)


def publish_cache(tmp_path):
    raw_x = np.arange(8 * 12, dtype=np.uint8).reshape(8, 3, 2, 2)
    raw_y = np.arange(8, dtype=np.int64)
    samples = Preprocessor((3, 2, 2), 10, (0.5,) * 3, (0.5,) * 3).transform(raw_x, raw_y)
    published = DatasetStorage(tmp_path / "dataset").materialize(dataset_config(), samples)
    root_bytes = published.manifest_path.read_bytes()
    root = json.loads(root_bytes)
    reference = root["shards"][0]
    shard_path = published.directory / reference["relative_shard_manifest_path"]
    shard_bytes = shard_path.read_bytes()
    shard = json.loads(shard_bytes)
    batch_bytes = {
        entry["relative_filename"]: (published.directory / entry["relative_filename"]).read_bytes()
        for entry in shard["batches"]
    }
    key = ShardCacheKey(published.dataset_build_id, published.dataset_manifest_hash, shard_id=0)
    cache = ShardCache(tmp_path / "cache")
    return (
        cache,
        cache.publish(key, root_bytes, shard_bytes, batch_bytes),
        (
            root_bytes,
            shard_bytes,
            batch_bytes,
        ),
    )


def assignment(**changes) -> StepAssignment:
    values = {
        "attempt_id": "attempt-1",
        "session_id": 4,
        "worker_id": 0,
        "operation_id": 9,
        "step_id": 0,
        "input_model_version": 0,
        "batch_id": 0,
        "batch_ordinal": 0,
        "expected_sample_count": 2,
    }
    values.update(changes)
    return StepAssignment(**values)


def adapter() -> PyTorchAdapter:
    torch.manual_seed(13)
    return PyTorchAdapter(SmallCNN(), functional.cross_entropy)


def test_cache_key_uses_full_build_and_manifest_identity():
    first = ShardCacheKey("build-a", "a" * 64, 1)
    assert first.directory_key != ShardCacheKey("build-b", "a" * 64, 1).directory_key
    assert first.directory_key != ShardCacheKey("build-a", "b" * 64, 1).directory_key
    assert first.directory_key != ShardCacheKey("build-a", "a" * 64, 2).directory_key


def test_cache_publishes_only_complete_verified_chain_and_loads_offline(tmp_path):
    cache, cached, source = publish_cache(tmp_path)
    root_bytes, shard_bytes, batch_bytes = source
    assert cache.load(cached.key).load_batch(0)[0].shape == (2, 3, 2, 2)

    source_batch = next((tmp_path / "dataset").rglob("batch-000000.npz"))
    source_batch.write_bytes(b"source is gone")
    assert cached.load_batch(0)[0].shape == (2, 3, 2, 2)

    incomplete = dict(batch_bytes)
    incomplete.pop(next(iter(incomplete)))
    other = ShardCache(tmp_path / "other-cache")
    with pytest.raises(ValueError, match="Incomplete"):
        other.publish(cached.key, root_bytes, shard_bytes, incomplete)
    corrupt = dict(batch_bytes)
    path = next(iter(corrupt))
    corrupt[path] = corrupt[path][:-1] + bytes([corrupt[path][-1] ^ 1])
    with pytest.raises(ValueError, match="hash"):
        other.publish(cached.key, root_bytes, shard_bytes, corrupt)
    assert not (tmp_path / "other-cache").exists()


def test_corrupt_cached_batch_is_unreadable(tmp_path):
    _, cached, _ = publish_cache(tmp_path)
    entry = cached.shard_manifest["batches"][0]
    path = cached.directory / entry["relative_filename"]
    path.write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        cached.load_batch(0)


def test_training_loop_uses_only_assigned_batch_and_exact_version(tmp_path):
    _, cached, _ = publish_cache(tmp_path)
    loop = TrainingLoop(adapter(), cached, model_version=0)
    with pytest.raises(ValueError, match="missing"):
        loop.compute(assignment(batch_id=9))
    with pytest.raises(ValueError, match="version"):
        loop.compute(assignment(input_model_version=1))
    computed = loop.compute(assignment())
    assert computed.assignment.batch_id == 0
    assert computed.local_gradient.sample_count == 2
    with pytest.raises(ValueError, match="awaits"):
        loop.compute(assignment())


def test_apply_updates_local_version_then_enables_exactly_one_ack(tmp_path):
    _, cached, _ = publish_cache(tmp_path)
    model_adapter = adapter()
    loop = TrainingLoop(model_adapter, cached, model_version=0)
    current_assignment = assignment()
    computed = loop.compute(current_assignment)
    with pytest.raises(ValueError, match="not ACK"):
        loop.consume_parameter_applied()
    current = model_adapter.export_parameters()
    canonical = TensorBundle(
        current.parameter_manifest_hash,
        tuple(
            value - np.float32(0.01) * delta
            for value, delta in zip(
                current.tensors, computed.local_gradient.bundle.tensors, strict=True
            )
        ),
    )
    eligibility = loop.apply_parameters(current_assignment, 1, canonical)
    assert loop.local_model_version == 1
    assert eligibility.model_version == 1
    assert loop.consume_parameter_applied() == eligibility
    with pytest.raises(ValueError, match="not ACK"):
        loop.consume_parameter_applied()


def test_application_failure_never_advances_version_or_ack(tmp_path, monkeypatch):
    _, cached, _ = publish_cache(tmp_path)
    model_adapter = adapter()
    loop = TrainingLoop(model_adapter, cached, model_version=0)
    current_assignment = assignment()
    loop.compute(current_assignment)
    bundle = model_adapter.export_parameters()

    def fail(_bundle):
        raise RuntimeError("injected apply failure")

    monkeypatch.setattr(model_adapter, "apply_parameters", fail)
    with pytest.raises(RuntimeError, match="injected"):
        loop.apply_parameters(current_assignment, 1, bundle)
    assert loop.local_model_version == 0
    with pytest.raises(ValueError, match="not ACK"):
        loop.consume_parameter_applied()


def test_worker_state_uses_only_canonical_session_states():
    state = WorkerState()
    for expected in (
        WorkerSessionState.REGISTERING,
        WorkerSessionState.PROVISIONING,
        WorkerSessionState.SHARD_READY,
        WorkerSessionState.MODEL_SYNCING,
        WorkerSessionState.READY,
    ):
        state.transition(expected)
        assert state.state is expected
    state.transition(WorkerSessionState.DISCONNECTED)
    with pytest.raises(ValueError, match="terminal"):
        state.transition(WorkerSessionState.FAILED)
    assert set(WorkerSessionState) == {
        WorkerSessionState.CONNECTING,
        WorkerSessionState.REGISTERING,
        WorkerSessionState.PROVISIONING,
        WorkerSessionState.SHARD_READY,
        WorkerSessionState.MODEL_SYNCING,
        WorkerSessionState.READY,
        WorkerSessionState.DISCONNECTED,
        WorkerSessionState.FAILED,
    }
