"""Verified Dataset Build materialization and atomic immutable publication."""

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np

from pbl4.common.hashing import canonical_json_bytes, sha256_bytes, sha256_file
from pbl4.dataset_manager.batch_builder import BatchBuilder
from pbl4.dataset_manager.config import DatasetBuildConfig
from pbl4.dataset_manager.manifest import DatasetManifest, ManifestBuilder
from pbl4.dataset_manager.partitioner import Partitioner
from pbl4.dataset_manager.preprocessing import Samples


@dataclass(frozen=True, slots=True)
class PublishedDatasetBuild:
    dataset_build_id: str
    dataset_manifest_hash: str
    directory: Path
    manifest_path: Path

    @property
    def lifecycle_state(self) -> str:
        # Catalog acknowledgement is deliberately outside this artifact phase.
        return "REGISTERING"


class DatasetStorage:
    """Local V1 store. Temporary and final directories share the same parent volume."""

    def __init__(self, root: Path):
        self._root = Path(root).resolve()
        self._temporary_root = self._root / ".tmp"

    @staticmethod
    def _directory_key(dataset_build_id: str) -> str:
        if not dataset_build_id:
            raise ValueError("Empty Dataset Build identity")
        return sha256_bytes(dataset_build_id.encode("utf-8"))

    @staticmethod
    def _safe(root: Path, relative: str) -> Path:
        candidate = (root / Path(*relative.split("/"))).resolve()
        if candidate == root or root not in candidate.parents:
            raise ValueError("Artifact path escapes build root")
        current = root
        for part in Path(*relative.split("/")).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Artifact path crosses a symlink")
        return candidate

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            if stream.write(content) != len(content):
                raise OSError("Short artifact write")
            stream.flush()
            os.fsync(stream.fileno())

    def materialize(self, config: DatasetBuildConfig, samples: Samples) -> PublishedDatasetBuild:
        if (
            samples.x.dtype != np.float32
            or samples.x.ndim != 4
            or tuple(samples.x.shape[1:]) != config.input_shape
            or samples.y.dtype != np.int64
            or samples.sample_ids.dtype != np.int64
            or samples.y.shape != (len(samples.x),)
            or samples.sample_ids.shape != (len(samples.x),)
            or len(np.unique(samples.sample_ids)) != len(samples.x)
            or not len(samples.x)
        ):
            raise ValueError("Invalid canonical sample collection")
        self._root.mkdir(parents=True, exist_ok=True)
        self._temporary_root.mkdir(exist_ok=True)
        final = self._root / self._directory_key(config.dataset_build_id)
        workspace = self._temporary_root / uuid4().hex
        workspace.mkdir()
        try:
            partitions = Partitioner().partition(
                len(samples.x), config.shard_count, config.partition_seed
            )
            physical = BatchBuilder().split(partitions, config.batch_size)
            manifest_builder = ManifestBuilder()
            shard_entries = []
            for shard_id, batches in enumerate(physical):
                batch_entries = []
                for batch_id, indices in enumerate(batches):
                    relative = f"shards/{shard_id:03d}/batch-{batch_id:06d}.npz"
                    path = self._safe(workspace, relative)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    entry = BatchBuilder().write(path, samples, indices)
                    batch_entries.append(
                        {"batch_id": batch_id, "relative_filename": relative, **entry}
                    )
                shard = manifest_builder.shard(
                    config.dataset_build_id, shard_id, tuple(batch_entries)
                )
                relative_manifest = f"shards/{shard_id:03d}/shard-manifest.json"
                self._write(self._safe(workspace, relative_manifest), shard.content)
                shard_entries.append(
                    {
                        "shard_id": shard_id,
                        "sample_count": sum(entry["sample_count"] for entry in batch_entries),
                        "batch_count": len(batch_entries),
                        "relative_shard_manifest_path": relative_manifest,
                        "shard_manifest_sha256": shard.sha256,
                    }
                )
            root = manifest_builder.root(
                config, len(samples.x), len(physical[0]), tuple(shard_entries)
            )
            self._write(workspace / "dataset-manifest.json", root.content)
            self._verify_tree(workspace, root.sha256)
            if final.exists():
                existing = self.load(config.dataset_build_id)
                if existing.dataset_manifest_hash != root.sha256:
                    raise ValueError("Immutable Dataset Build content conflict")
                return existing
            os.rename(workspace, final)
            self._fsync_directory(self._root)
            published = PublishedDatasetBuild(
                config.dataset_build_id,
                root.sha256,
                final,
                final / "dataset-manifest.json",
            )
            self.verify(published)
            return published
        finally:
            self._remove_owned_workspace(workspace)

    def load(self, dataset_build_id: str) -> PublishedDatasetBuild:
        directory = self._root / self._directory_key(dataset_build_id)
        manifest_path = directory / "dataset-manifest.json"
        if directory.is_symlink() or manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError("Published Dataset Build is unavailable")
        manifest = DatasetManifest(manifest_path.read_bytes())
        if manifest.value.get("dataset_build_id") != dataset_build_id:
            raise ValueError("Dataset Build identity mismatch")
        return PublishedDatasetBuild(
            dataset_build_id, manifest.dataset_manifest_hash, directory, manifest_path
        )

    def verify(self, published: PublishedDatasetBuild) -> DatasetManifest:
        expected = self._root / self._directory_key(published.dataset_build_id)
        if (
            published.directory.resolve() != expected
            or published.directory.is_symlink()
            or published.manifest_path != expected / "dataset-manifest.json"
        ):
            raise ValueError("Published paths do not belong to the Dataset Store")
        manifest = self._verify_tree(expected, published.dataset_manifest_hash)
        if manifest.value["dataset_build_id"] != published.dataset_build_id:
            raise ValueError("Dataset Build identity mismatch")
        return manifest

    def resolve_artifact(self, published: PublishedDatasetBuild, relative: str) -> Path:
        self.verify(published)
        path = self._safe(published.directory, relative)
        if path.is_symlink() or not path.is_file():
            raise ValueError("Artifact is not a regular published file")
        return path

    def _verify_tree(self, directory: Path, expected_root_hash: str) -> DatasetManifest:
        manifest_path = self._safe(directory, "dataset-manifest.json")
        manifest = DatasetManifest(manifest_path.read_bytes())
        if manifest.dataset_manifest_hash != expected_root_hash:
            raise ValueError("Corrupt Root Dataset Manifest")
        root = manifest.value
        if set(root) != {
            "schema_version",
            "dataset_build_id",
            "dataset_id",
            "name",
            "profile",
            "task_type",
            "input_shape",
            "dtype",
            "num_classes",
            "preprocessing",
            "batch_size",
            "shard_count",
            "partition_algorithm",
            "partition_seed",
            "sample_count",
            "batch_count_per_shard",
            "shards",
        }:
            raise ValueError("Invalid Root Dataset Manifest fields")
        shards = root.get("shards")
        if not isinstance(shards, list) or len(shards) != root.get("shard_count"):
            raise ValueError("Invalid Root Dataset Manifest")
        seen: set[int] = set()
        total = 0
        for shard_id, reference in enumerate(shards):
            if (
                set(reference)
                != {
                    "shard_id",
                    "sample_count",
                    "batch_count",
                    "relative_shard_manifest_path",
                    "shard_manifest_sha256",
                }
                or reference.get("shard_id") != shard_id
            ):
                raise ValueError("Unordered Shard Manifest reference")
            shard_path = self._safe(directory, reference["relative_shard_manifest_path"])
            if sha256_file(str(shard_path)) != reference["shard_manifest_sha256"]:
                raise ValueError("Corrupt Shard Manifest")
            raw = shard_path.read_bytes()
            shard = json.loads(raw)
            if canonical_json_bytes(shard) != raw:
                raise ValueError("Noncanonical Shard Manifest")
            batches = shard.get("batches")
            if (
                set(shard)
                != {"dataset_build_id", "shard_id", "sample_count", "batch_count", "batches"}
                or shard.get("dataset_build_id") != root.get("dataset_build_id")
                or shard.get("shard_id") != shard_id
                or not isinstance(batches, list)
                or len(batches) != root.get("batch_count_per_shard")
                or shard.get("batch_count") != len(batches)
            ):
                raise ValueError("Inconsistent Shard Manifest")
            shard_total = 0
            for batch_id, entry in enumerate(batches):
                if set(entry) != {
                    "batch_id",
                    "relative_filename",
                    "sample_count",
                    "byte_size",
                    "sha256",
                }:
                    raise ValueError("Invalid Batch entry fields")
                path = self._safe(directory, entry["relative_filename"])
                if (
                    entry.get("batch_id") != batch_id
                    or path.stat().st_size != entry["byte_size"]
                    or sha256_file(str(path)) != entry["sha256"]
                ):
                    raise ValueError("Corrupt physical batch")
                with np.load(path, allow_pickle=False) as batch:
                    if set(batch.files) != {"x", "y", "sample_ids"}:
                        raise ValueError("Invalid NPZ fields")
                    x, y, ids = batch["x"], batch["y"], batch["sample_ids"]
                if (
                    x.dtype != np.float32
                    or x.ndim != 4
                    or tuple(x.shape[1:]) != tuple(root["input_shape"])
                    or y.dtype != np.int64
                    or ids.dtype != np.int64
                    or y.shape != (len(x),)
                    or ids.shape != (len(x),)
                    or len(x) != entry["sample_count"]
                    or not len(x)
                ):
                    raise ValueError("Invalid canonical NPZ")
                values = {int(value) for value in ids}
                if len(values) != len(ids) or seen.intersection(values):
                    raise ValueError("Duplicated sample identity")
                seen.update(values)
                shard_total += len(x)
            if shard_total != shard.get("sample_count") or shard_total != reference["sample_count"]:
                raise ValueError("Shard sample count mismatch")
            total += shard_total
        if total != root.get("sample_count") or seen != set(range(total)):
            raise ValueError("Dataset coverage mismatch")
        return manifest

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name != "nt":
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

    def _remove_owned_workspace(self, workspace: Path) -> None:
        resolved = workspace.resolve()
        if resolved.parent != self._temporary_root.resolve():
            raise ValueError("Refusing to remove an unowned temporary directory")
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
