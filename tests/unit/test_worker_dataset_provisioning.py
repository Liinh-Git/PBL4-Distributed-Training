"""Unit tests for worker multi-shard provisioning flow and cache_scope (Task T3.2)."""

from __future__ import annotations

import io
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pbl4.common.errors import ProtocolError
from pbl4.common.work_unit import WorkUnitRef
from pbl4.protocol.messages import DatasetAssignment, ShardReady
from pbl4.worker.config import WorkerConfig
from pbl4.worker.process import WorkerProcess
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts


class MockResponse:
    status = 200

    def __init__(self, content: bytes):
        self._stream = io.BytesIO(content)

    def read(self, size=-1):
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class MockOpener:
    def __init__(self, responses: dict[str, bytes]):
        self.responses = responses
        self.requested_urls: list[str] = []

    def __call__(self, request, **_kwargs):
        url = request.full_url
        self.requested_urls.append(url)
        if url not in self.responses:
            raise OSError(f"Mock 404: {url}")
        return MockResponse(self.responses[url])


def build_responses(artifacts, base_url: str) -> dict[str, bytes]:
    responses = {
        f"{base_url}/manifest.json": artifacts.root_manifest_bytes,
    }
    for s_id in range(len(artifacts.shard_manifest_bytes)):
        responses[f"{base_url}/shards/{s_id}/manifest.json"] = artifacts.shard_manifest_bytes[s_id]
        shard_obj = artifacts.shard_manifest_dicts[s_id]
        for entry in shard_obj["batches"]:
            b_url = f"{base_url}/shards/{s_id}/batches/{entry['batch_id']}"
            responses[b_url] = artifacts.batch_bytes[entry["relative_filename"]]
    return responses


def test_dataset_assignment_cache_scope_wire_validation():
    base_dict = {
        "dataset_build_id": "build-1",
        "dataset_manifest_hash": "a" * 64,
        "shard_id": 0,
        "artifact_base_url": "http://dm/artifacts/v1/dataset-builds/build-1",
        "root_manifest_path": "manifest.json",
        "expected_shard_count": 3,
        "profile": "CNN_IMAGE_CLASSIFICATION_V1",
    }

    # Default without cache_scope
    msg_default = DatasetAssignment.from_dict(base_dict)
    assert msg_default.cache_scope == "assigned_shard"
    assert "cache_scope" not in msg_default.to_dict()

    # Explicit assigned_shard
    dict_assigned = {**base_dict, "cache_scope": "assigned_shard"}
    msg_assigned = DatasetAssignment.from_dict(dict_assigned)
    assert msg_assigned.cache_scope == "assigned_shard"
    assert msg_assigned.to_dict()["cache_scope"] == "assigned_shard"

    # Explicit all_shards
    dict_all = {**base_dict, "cache_scope": "all_shards"}
    msg_all = DatasetAssignment.from_dict(dict_all)
    assert msg_all.cache_scope == "all_shards"
    assert msg_all.to_dict()["cache_scope"] == "all_shards"

    # Invalid cache_scope rejected by enum validation
    with pytest.raises(ProtocolError, match="cache_scope is not a canonical enum value"):
        DatasetAssignment.from_dict({**base_dict, "cache_scope": "invalid_scope"})


def test_worker_provision_all_shards_success(tmp_path: Path, monkeypatch):
    dest = tmp_path / "artifacts"
    artifacts = create_synthetic_dataset_artifacts(
        destination_dir=dest,
        dataset_build_id="build-test-all-shards",
        shard_count=3,
        batches_per_shard=2,
        batch_size=4,
        input_shape=(3, 2, 2),
    )
    base_url = f"http://dm/artifacts/v1/dataset-builds/{artifacts.dataset_build_id}"
    responses = build_responses(artifacts, base_url)
    opener = MockOpener(responses)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    config = WorkerConfig(
        node_label="node-1",
        runtime_host="127.0.0.1",
        runtime_port=9000,
        cache_dir=str(tmp_path / "cache"),
    )
    worker = WorkerProcess(config, initialization_seed=42, opener=opener)

    # Mock worker client
    mock_client = MagicMock()
    mock_client.expected_workers = 3
    mock_client.worker_id = 0
    worker._client = mock_client

    assignment = DatasetAssignment.from_dict(
        {
            "dataset_build_id": artifacts.dataset_build_id,
            "dataset_manifest_hash": artifacts.dataset_manifest_hash,
            "shard_id": 0,
            "artifact_base_url": base_url,
            "root_manifest_path": "manifest.json",
            "expected_shard_count": 3,
            "profile": "CNN_IMAGE_CLASSIFICATION_V1",
            "cache_scope": "all_shards",
        }
    )

    worker._provision(assignment)

    # DatasetCache must be instantiated with all 3 shards
    assert worker.dataset_cache is not None
    assert worker.dataset_cache.shard_count == 3
    assert worker.dataset_cache.eligible_work_unit_count == 6
    assert 0 in worker.dataset_cache
    assert 1 in worker.dataset_cache
    assert 2 in worker.dataset_cache

    # Can load any work unit across shards
    x1, _y1, _ = worker.dataset_cache.load_work_unit(
        WorkUnitRef(shard_id=1, batch_id=0, sample_count=4)
    )
    assert x1.shape == (4, 3, 2, 2)

    # Standard SHARD_READY message was sent
    mock_client.send_shard_ready.assert_called_once()
    ready_msg = mock_client.send_shard_ready.call_args[0][0]
    assert isinstance(ready_msg, ShardReady)
    assert ready_msg.shard_id == 0
    assert ready_msg.dataset_build_id == artifacts.dataset_build_id
    assert ready_msg.dataset_manifest_hash == artifacts.dataset_manifest_hash

    # Worker 0 sends model init
    mock_client.send_model_manifest.assert_called_once()
    mock_client.send_model_init.assert_called_once()


def test_worker_provision_assigned_shard_legacy(tmp_path: Path, monkeypatch):
    dest = tmp_path / "artifacts"
    artifacts = create_synthetic_dataset_artifacts(
        destination_dir=dest,
        dataset_build_id="build-test-assigned-shard",
        shard_count=2,
        batches_per_shard=2,
        batch_size=4,
        input_shape=(3, 2, 2),
    )
    base_url = f"http://dm/artifacts/v1/dataset-builds/{artifacts.dataset_build_id}"
    responses = build_responses(artifacts, base_url)
    opener = MockOpener(responses)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    config = WorkerConfig(
        node_label="node-1",
        runtime_host="127.0.0.1",
        runtime_port=9000,
        cache_dir=str(tmp_path / "cache"),
    )
    worker = WorkerProcess(config, initialization_seed=42, opener=opener)

    mock_client = MagicMock()
    mock_client.expected_workers = 2
    mock_client.worker_id = 1
    worker._client = mock_client

    assignment = DatasetAssignment.from_dict(
        {
            "dataset_build_id": artifacts.dataset_build_id,
            "dataset_manifest_hash": artifacts.dataset_manifest_hash,
            "shard_id": 1,
            "artifact_base_url": base_url,
            "root_manifest_path": "manifest.json",
            "expected_shard_count": 2,
            "profile": "CNN_IMAGE_CLASSIFICATION_V1",
            "cache_scope": "assigned_shard",
        }
    )

    worker._provision(assignment)

    # DatasetCache should be None for legacy single-shard provisioning
    assert worker.dataset_cache is None

    # SHARD_READY was sent for shard 1
    mock_client.send_shard_ready.assert_called_once()
    ready_msg = mock_client.send_shard_ready.call_args[0][0]
    assert ready_msg.shard_id == 1

    # Worker 1 does not send model init
    mock_client.send_model_manifest.assert_called_once()
    mock_client.send_model_init.assert_not_called()


def test_worker_provision_all_shards_fails_if_any_shard_missing(tmp_path: Path, monkeypatch):
    dest = tmp_path / "artifacts"
    artifacts = create_synthetic_dataset_artifacts(
        destination_dir=dest,
        dataset_build_id="build-test-fail-shard",
        shard_count=3,
        batches_per_shard=2,
        batch_size=4,
        input_shape=(3, 2, 2),
    )
    base_url = f"http://dm/artifacts/v1/dataset-builds/{artifacts.dataset_build_id}"
    responses = build_responses(artifacts, base_url)
    # Remove shard 2's manifest to simulate a missing/failing shard
    del responses[f"{base_url}/shards/2/manifest.json"]

    opener = MockOpener(responses)
    monkeypatch.setattr(urllib.request, "urlopen", opener)

    config = WorkerConfig(
        node_label="node-1",
        runtime_host="127.0.0.1",
        runtime_port=9000,
        cache_dir=str(tmp_path / "cache"),
    )
    worker = WorkerProcess(config, initialization_seed=42, opener=opener)

    mock_client = MagicMock()
    mock_client.expected_workers = 3
    mock_client.worker_id = 0
    worker._client = mock_client

    assignment = DatasetAssignment.from_dict(
        {
            "dataset_build_id": artifacts.dataset_build_id,
            "dataset_manifest_hash": artifacts.dataset_manifest_hash,
            "shard_id": 0,
            "artifact_base_url": base_url,
            "root_manifest_path": "manifest.json",
            "expected_shard_count": 3,
            "profile": "CNN_IMAGE_CLASSIFICATION_V1",
            "cache_scope": "all_shards",
        }
    )

    with pytest.raises(ValueError, match="Artifact download failed after retry policy"):
        worker._provision(assignment)

    # ShardReady must NOT have been sent
    mock_client.send_shard_ready.assert_not_called()
    assert worker.dataset_cache is None
