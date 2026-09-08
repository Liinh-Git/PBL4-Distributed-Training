"""Framework-adapter tests with real PyTorch forward/backward execution."""

import numpy as np
import pytest
import torch
from torch.nn import functional as functional

from pbl4.adapter.base import TensorBundle
from pbl4.adapter.models.small_cnn import SmallCNN
from pbl4.adapter.pytorch_adapter import PyTorchAdapter


def adapter() -> PyTorchAdapter:
    torch.manual_seed(7)
    return PyTorchAdapter(SmallCNN(), functional.cross_entropy)


def batch() -> tuple[np.ndarray, np.ndarray]:
    generator = np.random.default_rng(11)
    return generator.normal(size=(3, 3, 2, 2)).astype(np.float32), np.array(
        [1, 4, 7], dtype=np.int64
    )


def test_parameter_manifest_is_stable_ordered_and_matches_export():
    first = adapter()
    second = adapter()
    assert first.manifest == second.manifest
    assert first.manifest.parameter_manifest_hash == second.manifest.parameter_manifest_hash
    assert [spec.tensor_id for spec in first.manifest.tensors] == list(
        range(len(first.manifest.tensors))
    )
    assert [spec.name for spec in first.manifest.tensors] == [
        "features.0.weight",
        "features.0.bias",
        "classifier.weight",
        "classifier.bias",
    ]
    bundle = first.export_parameters()
    assert bundle.parameter_manifest_hash == first.manifest.parameter_manifest_hash
    assert [array.shape for array in bundle.tensors] == [
        spec.shape for spec in first.manifest.tensors
    ]
    assert all(not array.flags.writeable for array in bundle.tensors)


def test_actual_backward_exports_all_gradients_and_zeroes_between_steps():
    model_adapter = adapter()
    x, y = batch()
    first = model_adapter.compute_loss_and_gradients(x, y)
    second = model_adapter.compute_loss_and_gradients(x, y)
    assert first.sample_count == len(x)
    assert first.loss == pytest.approx(second.loss)
    assert len(first.bundle.tensors) == len(model_adapter.manifest.tensors)
    for left, right, spec in zip(
        first.bundle.tensors,
        second.bundle.tensors,
        model_adapter.manifest.tensors,
        strict=True,
    ):
        assert left.shape == spec.shape
        np.testing.assert_allclose(left, right, rtol=0, atol=0)


def test_export_apply_round_trip_and_reject_malformed_bundle_atomically():
    model_adapter = adapter()
    original = model_adapter.export_parameters()
    changed = TensorBundle(
        original.parameter_manifest_hash,
        tuple(array + np.float32(0.25) for array in original.tensors),
    )
    model_adapter.apply_parameters(changed)
    for actual, expected in zip(
        model_adapter.export_parameters().tensors, changed.tensors, strict=True
    ):
        np.testing.assert_array_equal(actual, expected)

    before = model_adapter.export_parameters()
    malformed = TensorBundle("0" * 64, before.tensors)
    with pytest.raises(ValueError, match="Manifest"):
        model_adapter.apply_parameters(malformed)
    for actual, expected in zip(
        model_adapter.export_parameters().tensors, before.tensors, strict=True
    ):
        np.testing.assert_array_equal(actual, expected)


@pytest.mark.parametrize(
    ("x", "y"),
    [
        (np.zeros((0, 3, 2, 2), dtype=np.float32), np.zeros(0, dtype=np.int64)),
        (np.zeros((1, 3, 2, 2), dtype=np.float64), np.zeros(1, dtype=np.int64)),
        (np.zeros((1, 3, 2, 2), dtype=np.float32), np.zeros(1, dtype=np.int32)),
    ],
)
def test_adapter_rejects_noncanonical_local_batches(x, y):
    with pytest.raises(ValueError):
        adapter().compute_loss_and_gradients(x, y)


def test_small_cnn_is_only_a_multi_step_smoke_model():
    model_adapter = adapter()
    x, y = batch()
    for _ in range(3):
        gradient = model_adapter.compute_loss_and_gradients(x, y)
        current = model_adapter.export_parameters()
        updated = TensorBundle(
            current.parameter_manifest_hash,
            tuple(
                value - np.float32(0.01) * delta
                for value, delta in zip(current.tensors, gradient.bundle.tensors, strict=True)
            ),
        )
        model_adapter.apply_parameters(updated)
    assert np.isfinite(model_adapter.compute_loss_and_gradients(x, y).loss)
