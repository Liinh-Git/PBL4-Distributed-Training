"""Minimal synthetic dataset artifact generator for PBL4 consumer tests.

Generates valid canonical root manifests, shard manifests, and NPZ batches
without importing any Dataset Manager service implementation.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from pbl4.common.hashing import canonical_json_bytes, sha256_bytes


@dataclass(frozen=True, slots=True)
class SyntheticDatasetArtifacts:
    dataset_build_id: str
    dataset_manifest_hash: str
    root_manifest_bytes: bytes
    root_manifest_dict: dict[str, Any]
    shard_manifest_bytes: dict[int, bytes]
    shard_manifest_dicts: dict[int, dict[str, Any]]
    batch_bytes: dict[str, bytes]
    shard_batch_bytes: dict[int, dict[str, bytes]]
    directory: Path


def create_synthetic_dataset_artifacts(
    destination_dir: Path,
    *,
    dataset_build_id: str = "build-synthetic-test",
    shard_count: int = 2,
    batches_per_shard: int = 2,
    batch_size: int = 2,
    input_shape: tuple[int, int, int] = (3, 2, 2),
    num_classes: int = 10,
) -> SyntheticDatasetArtifacts:
    """Create minimal deterministic NPZ batches and canonical manifests on disk."""
    dest = Path(destination_dir).resolve()
    dest.mkdir(parents=True, exist_ok=True)

    batch_bytes_map: dict[str, bytes] = {}
    shard_batch_bytes_map: dict[int, dict[str, bytes]] = {}
    shard_manifest_bytes: dict[int, bytes] = {}
    shard_manifest_dicts: dict[int, dict[str, Any]] = {}
    shard_references: list[dict[str, Any]] = []

    for shard_id in range(shard_count):
        shard_dir = dest / "shards" / f"{shard_id:03d}"
        shard_dir.mkdir(parents=True, exist_ok=True)
        batch_entries: list[dict[str, Any]] = []
        shard_batches: dict[str, bytes] = {}

        for batch_id in range(batches_per_shard):
            rel_filename = f"shards/{shard_id:03d}/batch-{batch_id:06d}.npz"
            batch_path = dest / rel_filename

            # Create deterministic float32 tensor
            offset = (shard_id * batches_per_shard + batch_id) * batch_size
            x = np.arange(offset, offset + batch_size * np.prod(input_shape), dtype=np.float32)
            x = x.reshape((batch_size, *input_shape))
            y = np.arange(offset, offset + batch_size, dtype=np.int64) % num_classes
            sample_ids = np.arange(offset, offset + batch_size, dtype=np.int64)

            stream = io.BytesIO()
            np.savez(stream, x=x, y=y, sample_ids=sample_ids)
            content = stream.getvalue()
            batch_path.write_bytes(content)
            batch_bytes_map[rel_filename] = content
            shard_batches[rel_filename] = content

            batch_entries.append(
                {
                    "batch_id": batch_id,
                    "byte_size": len(content),
                    "relative_filename": rel_filename,
                    "sample_count": batch_size,
                    "sha256": sha256_bytes(content),
                }
            )

        shard_batch_bytes_map[shard_id] = shard_batches
        shard_obj = {
            "batch_count": len(batch_entries),
            "batches": batch_entries,
            "dataset_build_id": dataset_build_id,
            "sample_count": sum(e["sample_count"] for e in batch_entries),
            "shard_id": shard_id,
        }
        shard_bytes = canonical_json_bytes(shard_obj)
        shard_hash = sha256_bytes(shard_bytes)
        rel_shard_manifest = f"shards/{shard_id:03d}/shard-manifest.json"
        (dest / rel_shard_manifest).write_bytes(shard_bytes)
        shard_manifest_bytes[shard_id] = shard_bytes
        shard_manifest_dicts[shard_id] = shard_obj

        shard_references.append(
            {
                "batch_count": len(batch_entries),
                "relative_shard_manifest_path": rel_shard_manifest,
                "sample_count": sum(e["sample_count"] for e in batch_entries),
                "shard_id": shard_id,
                "shard_manifest_sha256": shard_hash,
            }
        )

    root_obj = {
        "batch_count_per_shard": batches_per_shard,
        "batch_size": batch_size,
        "dataset_build_id": dataset_build_id,
        "dataset_id": "cifar10",
        "dtype": "float32",
        "input_shape": list(input_shape),
        "name": "CIFAR-10",
        "num_classes": num_classes,
        "partition_algorithm": "seeded_permutation_round_robin",
        "partition_seed": 42,
        "preprocessing": {
            "channel_order": "NCHW",
            "mean": [0.5, 0.5, 0.5],
            "scale": "uint8_to_unit",
            "std": [0.5, 0.5, 0.5],
        },
        "profile": "CNN_IMAGE_CLASSIFICATION_V1",
        "sample_count": sum(ref["sample_count"] for ref in shard_references),
        "schema_version": 1,
        "shard_count": shard_count,
        "shards": shard_references,
        "task_type": "image_classification",
    }
    root_bytes = canonical_json_bytes(root_obj)
    manifest_hash = sha256_bytes(root_bytes)
    (dest / "dataset-manifest.json").write_bytes(root_bytes)

    return SyntheticDatasetArtifacts(
        dataset_build_id=dataset_build_id,
        dataset_manifest_hash=manifest_hash,
        root_manifest_bytes=root_bytes,
        root_manifest_dict=root_obj,
        shard_manifest_bytes=shard_manifest_bytes,
        shard_manifest_dicts=shard_manifest_dicts,
        batch_bytes=batch_bytes_map,
        shard_batch_bytes=shard_batch_bytes_map,
        directory=dest,
    )
