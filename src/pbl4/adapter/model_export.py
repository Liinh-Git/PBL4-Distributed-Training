"""Load verified model exports using the existing framework adapter/model factory."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
from torch.nn import CrossEntropyLoss

from pbl4.adapter.base import TensorBundle
from pbl4.adapter.models.factory import build_model
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.common.hashing import canonical_json_hash, sha256_bytes
from pbl4.common.model_profiles import MODEL_PROFILES
from pbl4.protocol.parameter_manifest import ParameterManifest


def load_exported_model(path: str | Path, *, device: str = "cpu"):
    """Return an eval-mode model; no Runtime imports or pickle decoding."""
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("Duplicate export entries")
        metadata = json.loads(archive.read("checkpoint.json"))
        contract = json.loads(archive.read("resolved-contract.json"))
        manifest = ParameterManifest.from_dict(json.loads(archive.read("parameter-manifest.json")))
        payload = archive.read("model.bin")
    if canonical_json_hash(contract) != metadata["contract_hash"]:
        raise ValueError("Export contract hash mismatch")
    model_info = metadata["model"]
    if (
        model_info["encoding"] != "fp32_le_v1"
        or sha256_bytes(payload) != model_info["payload_sha256"]
        or len(payload) != model_info["payload_size_bytes"]
        or len(payload) != manifest.total_numel * 4
        or manifest.parameter_manifest_hash != model_info["parameter_manifest_hash"]
        or MODEL_PROFILES.get(metadata["model_id"]) != metadata["model_profile"]
    ):
        raise ValueError("Export weights/manifest/profile mismatch")
    model = build_model(metadata["model_id"], initialization_seed=0, device=device)
    if tuple(model.buffers()):
        raise ValueError("Model has buffers that this export format cannot restore")
    adapter = PyTorchAdapter(model, CrossEntropyLoss(), local_gradient_reduction="mean")
    flat = np.frombuffer(payload, dtype="<f4")
    tensors = []
    for entry in manifest.parameters:
        offset = entry.byte_offset // 4
        tensors.append(flat[offset : offset + entry.numel].reshape(entry.shape))
    adapter.apply_parameters(TensorBundle(manifest.parameter_manifest_hash, tuple(tensors)))
    model.eval()
    return model
