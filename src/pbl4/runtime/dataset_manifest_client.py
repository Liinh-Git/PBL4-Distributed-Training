"""Pre-training root Dataset Manifest retrieval and contract pinning over HTTP."""

import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import quote

from pbl4.common.hashing import canonical_json_bytes, sha256_bytes


@dataclass(frozen=True, slots=True)
class PinnedDatasetManifest:
    dataset_build_id: str
    dataset_manifest_hash: str
    value: dict[str, object]

    @property
    def shard_count(self) -> int:
        return int(self.value["shard_count"])

    @property
    def batch_count_per_shard(self) -> int:
        return int(self.value["batch_count_per_shard"])


class DatasetManifestClient:
    def __init__(
        self,
        dataset_manager_base_url: str,
        *,
        timeout_seconds: float = 10.0,
        maximum_bytes: int = 1024 * 1024,
        opener: Callable[..., object] = urllib.request.urlopen,
    ):
        if (
            not dataset_manager_base_url.startswith(("http://", "https://"))
            or timeout_seconds <= 0
            or maximum_bytes <= 0
        ):
            raise ValueError("Invalid Dataset Manifest client configuration")
        self._base_url = dataset_manager_base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._maximum_bytes = maximum_bytes
        self._opener = opener

    def pin(
        self, dataset_build_id: str, expected_dataset_manifest_hash: str
    ) -> PinnedDatasetManifest:
        if (
            not dataset_build_id
            or re.fullmatch(r"[0-9a-f]{64}", expected_dataset_manifest_hash) is None
        ):
            raise ValueError("Invalid pinned Dataset Build identity")
        url = (
            f"{self._base_url}/artifacts/v1/dataset-builds/"
            f"{quote(dataset_build_id, safe='')}/manifest.json"
        )
        request = urllib.request.Request(url, headers={"Accept": "application/json"})
        with self._opener(request, timeout=self._timeout) as response:
            if getattr(response, "status", 200) != 200:
                raise OSError("Root Dataset Manifest endpoint did not return HTTP 200")
            content = response.read(self._maximum_bytes + 1)
        if len(content) > self._maximum_bytes:
            raise ValueError("Root Dataset Manifest exceeds configured size limit")
        if sha256_bytes(content) != expected_dataset_manifest_hash:
            raise ValueError("Root Dataset Manifest hash mismatch")
        value = json.loads(content)
        shards = value.get("shards") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or canonical_json_bytes(value) != content
            or value.get("dataset_build_id") != dataset_build_id
            or not isinstance(shards, list)
            or type(value.get("shard_count")) is not int
            or value["shard_count"] <= 0
            or value["shard_count"] != len(shards)
            or any(
                not isinstance(reference, dict)
                or reference.get("shard_id") != shard_id
                or re.fullmatch(r"[0-9a-f]{64}", reference.get("shard_manifest_sha256", "")) is None
                for shard_id, reference in enumerate(shards)
            )
            or type(value.get("batch_count_per_shard")) is not int
            or value["batch_count_per_shard"] <= 0
        ):
            raise ValueError("Invalid pinned Root Dataset Manifest")
        return PinnedDatasetManifest(dataset_build_id, expected_dataset_manifest_hash, value)
