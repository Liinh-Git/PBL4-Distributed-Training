"""Verified local shard publication; training reads only complete cache entries."""

import io
import json
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import numpy as np

from pbl4.common.hashing import canonical_json_bytes, sha256_bytes, sha256_canonical_json


@dataclass(frozen=True, slots=True)
class ShardCacheKey:
    dataset_build_id: str
    dataset_manifest_hash: str
    shard_id: int

    def __post_init__(self) -> None:
        if (
            not self.dataset_build_id
            or re.fullmatch(r"[0-9a-f]{64}", self.dataset_manifest_hash) is None
            or type(self.shard_id) is not int
            or self.shard_id < 0
        ):
            raise ValueError("Invalid full shard cache identity")

    @property
    def directory_key(self) -> str:
        return sha256_canonical_json(
            [self.dataset_build_id, self.dataset_manifest_hash, self.shard_id]
        )


@dataclass(frozen=True, slots=True)
class CachedShard:
    key: ShardCacheKey
    directory: Path
    root_manifest: dict[str, object]
    shard_manifest: dict[str, object]

    def load_batch(self, batch_id: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if type(batch_id) is not int or batch_id < 0:
            raise ValueError("Invalid assigned batch ID")
        batches = self.shard_manifest["batches"]
        if batch_id >= len(batches) or batches[batch_id]["batch_id"] != batch_id:
            raise ValueError("Assigned physical batch is missing")
        entry = batches[batch_id]
        path = _safe(self.directory, entry["relative_filename"])
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != entry["byte_size"]
            or sha256_bytes(path.read_bytes()) != entry["sha256"]
        ):
            raise ValueError("Cached physical batch failed integrity verification")
        with np.load(path, allow_pickle=False) as batch:
            if set(batch.files) != {"x", "y", "sample_ids"}:
                raise ValueError("Invalid cached NPZ fields")
            x, y, sample_ids = batch["x"], batch["y"], batch["sample_ids"]
        if (
            x.dtype != np.float32
            or x.ndim != 4
            or tuple(x.shape[1:]) != tuple(self.root_manifest["input_shape"])
            or y.dtype != np.int64
            or sample_ids.dtype != np.int64
            or y.shape != (len(x),)
            or sample_ids.shape != (len(x),)
            or len(x) != entry["sample_count"]
            or not len(x)
        ):
            raise ValueError("Invalid cached NPZ representation")
        return x, y, sample_ids


def _safe(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Unsafe cache-relative path")
    parts = Path(*relative.split("/")).parts
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise ValueError("Unsafe cache-relative path")
    candidate = (root / Path(*parts)).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError("Cache path escapes entry")
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Cache path crosses symlink")
    return candidate


class ShardCache:
    def __init__(self, root: Path):
        self._root = Path(root).resolve()
        self._parts = self._root / ".part"

    def publish(
        self,
        key: ShardCacheKey,
        root_bytes: bytes,
        shard_bytes: bytes,
        batch_bytes: dict[str, bytes],
    ) -> CachedShard:
        root = self._parse_canonical(root_bytes)
        if (
            sha256_bytes(root_bytes) != key.dataset_manifest_hash
            or root.get("dataset_build_id") != key.dataset_build_id
        ):
            raise ValueError("Root Dataset Manifest identity/hash mismatch")
        references = root.get("shards")
        if not isinstance(references, list) or key.shard_id >= len(references):
            raise ValueError("Assigned shard is absent from Root Dataset Manifest")
        reference = references[key.shard_id]
        if reference.get("shard_id") != key.shard_id or sha256_bytes(shard_bytes) != reference.get(
            "shard_manifest_sha256"
        ):
            raise ValueError("Shard Manifest identity/hash mismatch")
        shard = self._parse_canonical(shard_bytes)
        batches = shard.get("batches")
        if (
            shard.get("dataset_build_id") != key.dataset_build_id
            or shard.get("shard_id") != key.shard_id
            or not isinstance(batches, list)
            or shard.get("batch_count") != len(batches)
        ):
            raise ValueError("Invalid assigned Shard Manifest")
        expected_paths = {entry.get("relative_filename") for entry in batches}
        if None in expected_paths or set(batch_bytes) != expected_paths:
            raise ValueError("Incomplete or unexpected physical batch set")
        for batch_id, entry in enumerate(batches):
            content = bytes(batch_bytes[entry["relative_filename"]])
            if (
                entry.get("batch_id") != batch_id
                or len(content) != entry.get("byte_size")
                or sha256_bytes(content) != entry.get("sha256")
            ):
                raise ValueError("Physical batch identity/hash mismatch")
            self._validate_npz(content, root, entry)
        self._root.mkdir(parents=True, exist_ok=True)
        self._parts.mkdir(exist_ok=True)
        final = self._root / key.directory_key
        workspace = self._parts / uuid4().hex
        workspace.mkdir()
        try:
            self._write(workspace / "dataset-manifest.json", root_bytes)
            self._write(workspace / "shard-manifest.json", shard_bytes)
            for relative, content in batch_bytes.items():
                self._write(_safe(workspace, relative), bytes(content))
            if final.exists():
                existing = self.load(key)
                if existing.root_manifest != root or existing.shard_manifest != shard:
                    raise ValueError("Immutable cache entry conflict")
                return existing
            for attempt in range(5):
                try:
                    os.rename(workspace, final)
                    break
                except OSError as exc:
                    if final.exists():
                        existing = self.load(key)
                        if existing.root_manifest != root or existing.shard_manifest != shard:
                            raise ValueError("Immutable cache entry conflict") from exc
                        return existing
                    if attempt == 4:
                        raise
                    time.sleep(0.01 * (2**attempt))
            cached = CachedShard(key, final, root, shard)
            self.verify(cached)
            return cached
        finally:
            resolved = workspace.resolve()
            if resolved.parent != self._parts.resolve():
                raise ValueError("Refusing to remove an unowned partial cache entry")
            if workspace.exists():
                shutil.rmtree(workspace, ignore_errors=True)

    def load(self, key: ShardCacheKey) -> CachedShard:
        directory = self._root / key.directory_key
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Verified shard cache entry is unavailable")
        root_path = directory / "dataset-manifest.json"
        shard_path = directory / "shard-manifest.json"
        root_bytes, shard_bytes = root_path.read_bytes(), shard_path.read_bytes()
        root, shard = self._parse_canonical(root_bytes), self._parse_canonical(shard_bytes)
        references = root.get("shards")
        if (
            sha256_bytes(root_bytes) != key.dataset_manifest_hash
            or root.get("dataset_build_id") != key.dataset_build_id
            or not isinstance(references, list)
            or key.shard_id >= len(references)
        ):
            raise ValueError("Cached Root Dataset Manifest identity/hash mismatch")
        reference = references[key.shard_id]
        if (
            reference.get("shard_id") != key.shard_id
            or sha256_bytes(shard_bytes) != reference.get("shard_manifest_sha256")
            or shard.get("dataset_build_id") != key.dataset_build_id
            or shard.get("shard_id") != key.shard_id
        ):
            raise ValueError("Cached Shard Manifest identity/hash mismatch")
        cached = CachedShard(key, directory, root, shard)
        self.verify(cached)
        return cached

    def verify(self, cached: CachedShard) -> None:
        if cached.directory.resolve() != self._root / cached.key.directory_key:
            raise ValueError("Cache entry is outside the configured root")
        seen: set[int] = set()
        for entry in cached.shard_manifest["batches"]:
            _, _, sample_ids = cached.load_batch(entry["batch_id"])
            values = {int(value) for value in sample_ids}
            if len(values) != len(sample_ids) or seen.intersection(values):
                raise ValueError("Duplicate sample identity in cached shard")
            seen.update(values)
        if len(seen) != cached.shard_manifest["sample_count"]:
            raise ValueError("Cached shard sample coverage mismatch")

    @staticmethod
    def _parse_canonical(content: bytes) -> dict[str, object]:
        value = json.loads(content)
        if not isinstance(value, dict) or canonical_json_bytes(value) != content:
            raise ValueError("Manifest is not a canonical JSON object")
        return value

    @staticmethod
    def _validate_npz(content: bytes, root: dict, entry: dict) -> None:
        with np.load(io.BytesIO(content), allow_pickle=False) as batch:
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
            raise ValueError("Invalid canonical physical batch")

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            if stream.write(content) != len(content):
                raise OSError("Short cache write")
            stream.flush()
            os.fsync(stream.fileno())
