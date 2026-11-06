"""Convert Worker tensor bundles to and from the existing flat FP32 payload."""

import numpy as np

from pbl4.adapter.base import ModelAdapter, TensorBundle


def flatten_bundle(bundle: TensorBundle) -> bytes:
    return (
        np.concatenate([value.reshape(-1) for value in bundle.tensors])
        .astype("<f4", copy=False)
        .tobytes()
    )


def bundle_from_bytes(data: bytes, adapter: ModelAdapter) -> TensorBundle:
    flat = np.frombuffer(data, dtype="<f4")
    if flat.size != adapter.manifest.total_numel:
        raise ValueError("Canonical parameter transfer has the wrong size")
    tensors = tuple(
        flat[item.byte_offset // 4 : (item.byte_offset + item.byte_length) // 4]
        .reshape(item.shape)
        .astype(np.float32, copy=True)
        for item in adapter.manifest.parameters
    )
    return TensorBundle(adapter.manifest.parameter_manifest_hash, tensors)
