"""Standard-library HTTP provisioning into a verified immutable local ShardCache."""

import json
import os
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from pbl4.common.hashing import canonical_json_bytes, sha256_bytes
from pbl4.worker.shard_cache import CachedShard, ShardCache, ShardCacheKey


@dataclass(frozen=True, slots=True)
class ShardDownloadResult:
    shard: CachedShard
    cache_reused: bool
    bytes_downloaded: int


class ShardDownloader:
    def __init__(
        self,
        artifact_base_url: str,
        cache: ShardCache,
        temporary_root: Path,
        *,
        timeout_seconds: float = 15.0,
        retries: int = 3,
        chunk_size: int = 1024 * 1024,
        opener: Callable[..., object] = urllib.request.urlopen,
    ):
        if (
            not artifact_base_url.startswith(("http://", "https://"))
            or timeout_seconds <= 0
            or retries <= 0
            or chunk_size <= 0
        ):
            raise ValueError("Invalid shard downloader configuration")
        self._base_url = artifact_base_url.rstrip("/")
        self._cache = cache
        self._temporary_root = Path(temporary_root).resolve()
        self._timeout = timeout_seconds
        self._retries = retries
        self._chunk_size = chunk_size
        self._opener = opener

    def provision(self, key: ShardCacheKey) -> ShardDownloadResult:
        try:
            return ShardDownloadResult(self._cache.load(key), True, 0)
        except (OSError, ValueError):
            pass
        build = quote(key.dataset_build_id, safe="")
        if not self._base_url.endswith(f"/{build}"):
            raise ValueError("artifact_base_url does not match dataset_build_id")
        root_url = f"{self._base_url}/manifest.json"
        root_bytes = self._fetch(root_url, key.dataset_manifest_hash)
        root = self._canonical_object(root_bytes)
        references = root.get("shards")
        if (
            root.get("dataset_build_id") != key.dataset_build_id
            or not isinstance(references, list)
            or key.shard_id >= len(references)
        ):
            raise ValueError("Root Dataset Manifest does not contain the assigned shard")
        reference = references[key.shard_id]
        if (
            not isinstance(reference, dict)
            or reference.get("shard_id") != key.shard_id
            or not isinstance(reference.get("shard_manifest_sha256"), str)
        ):
            raise ValueError("Root Dataset Manifest contains an invalid shard reference")
        shard_url = f"{self._base_url}/shards/{key.shard_id}/manifest.json"
        shard_bytes = self._fetch(shard_url, reference["shard_manifest_sha256"])
        shard = self._canonical_object(shard_bytes)
        if (
            shard.get("dataset_build_id") != key.dataset_build_id
            or shard.get("shard_id") != key.shard_id
            or not isinstance(shard.get("batches"), list)
        ):
            raise ValueError("Downloaded Shard Manifest identity mismatch")
        batch_bytes: dict[str, bytes] = {}
        downloaded = len(root_bytes) + len(shard_bytes)
        for entry in shard["batches"]:
            if not isinstance(entry, dict):
                raise ValueError("Shard Manifest contains an invalid batch reference")
            batch_url = f"{self._base_url}/shards/{key.shard_id}/batches/{entry['batch_id']}"
            content = self._fetch(batch_url, entry["sha256"], entry["byte_size"])
            batch_bytes[entry["relative_filename"]] = content
            downloaded += len(content)
        cached = self._cache.publish(key, root_bytes, shard_bytes, batch_bytes)
        return ShardDownloadResult(cached, False, downloaded)

    def _fetch(self, url: str, expected_hash: str, expected_size: int | None = None) -> bytes:
        self._temporary_root.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for _ in range(self._retries):
            temporary = self._temporary_root / f"{uuid4().hex}.part"
            try:
                total = 0
                request = urllib.request.Request(url, headers={"Accept": "*/*"})
                with (
                    self._opener(request, timeout=self._timeout) as response,
                    temporary.open("xb") as stream,
                ):
                    if getattr(response, "status", 200) != 200:
                        raise OSError("Artifact endpoint did not return HTTP 200")
                    while chunk := response.read(self._chunk_size):
                        total += len(chunk)
                        if expected_size is not None and total > expected_size:
                            raise ValueError("Artifact exceeds manifest byte_size")
                        stream.write(chunk)
                    stream.flush()
                    os.fsync(stream.fileno())
                content = temporary.read_bytes()
                if (expected_size is not None and len(content) != expected_size) or sha256_bytes(
                    content
                ) != expected_hash:
                    raise ValueError("Downloaded artifact integrity mismatch")
                return content
            except Exception as exc:
                last_error = exc
            finally:
                if temporary.exists():
                    temporary.unlink()
        raise ValueError("Artifact download failed after retry policy") from last_error

    @staticmethod
    def _canonical_object(content: bytes) -> dict[str, object]:
        value = json.loads(content)
        if not isinstance(value, dict) or canonical_json_bytes(value) != content:
            raise ValueError("Downloaded manifest is not canonical JSON")
        return value
