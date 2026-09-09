"""Framework-adapter tests with real PyTorch forward/backward execution."""

import json

import numpy as np
import pytest
import torch
from torch.nn import functional as functional

from pbl4.adapter.base import TensorBundle
from pbl4.adapter.models.small_cnn import SmallCNN
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.common.hashing import sha256_bytes
from pbl4.protocol.parameter_manifest import ParameterManifest

F = functional  # short alias used in Issue-D tests


def adapter() -> PyTorchAdapter:
    torch.manual_seed(7)
    return PyTorchAdapter(
        SmallCNN(),
        functional.cross_entropy,
        local_gradient_reduction="mean",
    )


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
    assert [spec.tensor_id for spec in first.manifest.parameters] == list(
        range(len(first.manifest.parameters))
    )
    assert [spec.name for spec in first.manifest.parameters] == [
        "features.0.weight",
        "features.0.bias",
        "classifier.weight",
        "classifier.bias",
    ]
    bundle = first.export_parameters()
    assert bundle.parameter_manifest_hash == first.manifest.parameter_manifest_hash
    assert [array.shape for array in bundle.tensors] == [
        spec.shape for spec in first.manifest.parameters
    ]
    assert all(not array.flags.writeable for array in bundle.tensors)


def test_actual_backward_exports_all_gradients_and_zeroes_between_steps():
    model_adapter = adapter()
    x, y = batch()
    first = model_adapter.compute_loss_and_gradients(x, y)
    second = model_adapter.compute_loss_and_gradients(x, y)
    assert first.sample_count == len(x)
    assert first.loss == pytest.approx(second.loss)
    assert len(first.bundle.tensors) == len(model_adapter.manifest.parameters)
    for left, right, spec in zip(
        first.bundle.tensors,
        second.bundle.tensors,
        model_adapter.manifest.parameters,
        strict=True,
    ):
        assert left.shape == spec.shape
        np.testing.assert_allclose(left, right, rtol=0, atol=0)


def test_adapter_and_protocol_share_one_canonical_parameter_manifest():
    manifest = adapter().manifest
    expected = {
        "schema_version": 1,
        "total_numel": 162,
        "total_bytes": 648,
        "parameters": [
            {
                "tensor_id": 0,
                "name": "features.0.weight",
                "shape": [4, 3, 3, 3],
                "dtype": "float32",
                "numel": 108,
                "byte_offset": 0,
                "byte_length": 432,
            },
            {
                "tensor_id": 1,
                "name": "features.0.bias",
                "shape": [4],
                "dtype": "float32",
                "numel": 4,
                "byte_offset": 432,
                "byte_length": 16,
            },
            {
                "tensor_id": 2,
                "name": "classifier.weight",
                "shape": [10, 4],
                "dtype": "float32",
                "numel": 40,
                "byte_offset": 448,
                "byte_length": 160,
            },
            {
                "tensor_id": 3,
                "name": "classifier.bias",
                "shape": [10],
                "dtype": "float32",
                "numel": 10,
                "byte_offset": 608,
                "byte_length": 40,
            },
        ],
    }
    canonical = json.dumps(
        expected,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    assert isinstance(manifest, ParameterManifest)
    assert manifest.content_dict() == expected
    assert manifest.canonical_bytes() == canonical
    assert manifest.parameter_manifest_hash == sha256_bytes(canonical)
    assert ParameterManifest.from_dict(manifest.to_dict()) == manifest


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


# ── Issue D: Local gradient mean-semantics tests ───────────────────────────────


def test_d1_local_gradient_matches_mean_reduction_reference():
    """D1: adapter gradient equals direct PyTorch mean-loss backward."""
    torch.manual_seed(99)
    model = SmallCNN()
    model_adapter = PyTorchAdapter(
        model,
        F.cross_entropy,
        local_gradient_reduction="mean",
    )
    x, y = batch()

    result = model_adapter.compute_loss_and_gradients(x, y)

    # Recompute reference with explicit mean reduction
    device = next(model.parameters()).device
    inputs = torch.from_numpy(np.ascontiguousarray(x)).to(device)
    labels = torch.from_numpy(np.ascontiguousarray(y)).to(device)
    model.zero_grad(set_to_none=True)
    ref_loss = F.cross_entropy(model(inputs), labels, reduction="mean")
    ref_loss.backward()
    ref_grads = [p.grad.detach().cpu().numpy().copy() for p in model.parameters()]

    for actual, reference in zip(result.bundle.tensors, ref_grads, strict=True):
        np.testing.assert_allclose(actual, reference, rtol=1e-5, atol=1e-6)


def test_d2_non_mean_reduction_is_rejected():
    """D2: summed local gradients cannot be configured as the distributed contract."""

    def summed_loss(logits, labels):
        return F.cross_entropy(logits, labels, reduction="sum")

    with pytest.raises(ValueError, match="mean"):
        PyTorchAdapter(
            SmallCNN(),
            summed_loss,
            local_gradient_reduction="sum",
        )

    PyTorchAdapter(
        SmallCNN(),
        F.cross_entropy,
        local_gradient_reduction="mean",
    )


def test_d3_weighted_aggregation_equivalence():
    """D3: worker mean-gradients + Runtime weighted average == full-batch gradient."""
    torch.manual_seed(77)
    model = SmallCNN()

    rng = np.random.default_rng(42)
    b1 = 2
    b2 = 3
    x_full = rng.normal(size=(b1 + b2, 3, 2, 2)).astype(np.float32)
    y_full = rng.integers(0, 10, size=b1 + b2).astype(np.int64)

    # Worker-1 gradient on batch 1
    adapter1 = PyTorchAdapter(
        model,
        F.cross_entropy,
        local_gradient_reduction="mean",
    )
    grad1 = adapter1.compute_loss_and_gradients(x_full[:b1], y_full[:b1])

    # Worker-2 gradient on batch 2 (same model params — share weight via export/apply)
    adapter2 = PyTorchAdapter(
        model,
        F.cross_entropy,
        local_gradient_reduction="mean",
    )
    grad2 = adapter2.compute_loss_and_gradients(x_full[b1:], y_full[b1:])

    # Runtime weighted aggregation: g = sum(b_i * g_i) / sum(b_i)
    total = b1 + b2
    agg = [
        (b1 * g1 + b2 * g2) / total
        for g1, g2 in zip(grad1.bundle.tensors, grad2.bundle.tensors, strict=True)
    ]

    # Reference: single full-batch mean gradient
    device = next(model.parameters()).device
    model.zero_grad(set_to_none=True)
    inputs = torch.from_numpy(np.ascontiguousarray(x_full)).to(device)
    labels = torch.from_numpy(np.ascontiguousarray(y_full)).to(device)
    ref_loss = F.cross_entropy(model(inputs), labels, reduction="mean")
    ref_loss.backward()
    ref_grads = [p.grad.detach().cpu().numpy().copy() for p in model.parameters()]

    for actual, reference in zip(agg, ref_grads, strict=True):
        np.testing.assert_allclose(actual, reference, rtol=1e-4, atol=1e-5)
