"""Worker-local assigned-batch, cache, version, application, and ACK tests."""

import numpy as np
import pytest
import torch
from torch.nn import functional as functional

from pbl4.adapter.base import TensorBundle
from pbl4.adapter.models.small_cnn import SmallCNN
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.training_loop import StepAssignment, TrainingLoop
from pbl4.worker.worker_state import WorkerSessionState, WorkerState
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts


def publish_cache(tmp_path):
    data = create_synthetic_dataset_artifacts(
        tmp_path / "dataset",
        dataset_build_id="build-worker-test",
        shard_count=2,
        batches_per_shard=2,
        batch_size=2,
        input_shape=(3, 2, 2),
    )
    key = ShardCacheKey(data.dataset_build_id, data.dataset_manifest_hash, shard_id=0)
    cache = ShardCache(tmp_path / "cache")
    shard_batches = data.shard_batch_bytes[0]
    return (
        cache,
        cache.publish(
            key,
            data.root_manifest_bytes,
            data.shard_manifest_bytes[0],
            shard_batches,
        ),
        (
            data.root_manifest_bytes,
            data.shard_manifest_bytes[0],
            shard_batches,
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
        "shard_id": 0,
        "batch_id": 0,
        "batch_ordinal": 0,
        "expected_sample_count": 2,
    }
    values.update(changes)
    return StepAssignment(**values)


def adapter() -> PyTorchAdapter:
    torch.manual_seed(13)
    return PyTorchAdapter(
        SmallCNN(),
        functional.cross_entropy,
        local_gradient_reduction="mean",
    )


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


# ── Issue B: Shard identity validation tests ──────────────────────────────────


def test_b1_correct_shard_id_allows_compute(tmp_path):
    """B1: assignment shard_id == cached shard_id → compute succeeds."""
    _, cached, _ = publish_cache(tmp_path)
    assert cached.key.shard_id == 0
    loop = TrainingLoop(adapter(), cached, model_version=0)
    computed = loop.compute(assignment(shard_id=0))
    assert computed.local_gradient.sample_count == 2


def test_b2_wrong_shard_id_rejects_before_adapter_call(tmp_path, monkeypatch):
    """B2: assignment shard_id != cached shard_id → rejected before adapter forward/backward."""
    _, cached, _ = publish_cache(tmp_path)
    assert cached.key.shard_id == 0
    model_adapter = adapter()
    compute_calls = []

    original_compute = model_adapter.compute_loss_and_gradients

    def spy_compute(x, y):
        compute_calls.append((x, y))
        return original_compute(x, y)

    monkeypatch.setattr(model_adapter, "compute_loss_and_gradients", spy_compute)
    loop = TrainingLoop(model_adapter, cached, model_version=0)
    with pytest.raises(ValueError, match="shard"):
        loop.compute(assignment(shard_id=1, expected_sample_count=2))
    # Adapter must NOT have been called
    assert compute_calls == []


def test_b3_invalid_shard_id_rejected_by_assignment_validation():
    """B3: negative or non-int shard_id is rejected at StepAssignment construction."""
    with pytest.raises(ValueError, match="Invalid STEP_START"):
        assignment(shard_id=-1)
    with pytest.raises(ValueError, match="Invalid STEP_START"):
        assignment(shard_id="0")  # type: ignore[arg-type]


def test_b4_normal_training_flow_still_passes(tmp_path):
    """B4: correct shard_id → full compute/apply/ack flow works unchanged."""
    _, cached, _ = publish_cache(tmp_path)
    model_adapter = adapter()
    loop = TrainingLoop(model_adapter, cached, model_version=0)
    current_assignment = assignment(shard_id=0)
    computed = loop.compute(current_assignment)
    assert computed.assignment is current_assignment
    current = model_adapter.export_parameters()
    from pbl4.adapter.base import TensorBundle

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
