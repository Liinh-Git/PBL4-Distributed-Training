"""Unit tests for worker computation timing and compute_ms transmission (Task T4.3)."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pbl4.protocol.messages import DatasetAssignment, StepStart
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

    def __call__(self, request, **_kwargs):
        return MockResponse(self.responses[request.full_url])


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


@pytest.fixture
def provisioned_worker(tmp_path: Path):
    dest = tmp_path / "artifacts"
    artifacts = create_synthetic_dataset_artifacts(
        destination_dir=dest,
        dataset_build_id="build-timing-test",
        shard_count=2,
        batches_per_shard=2,
        batch_size=4,
        input_shape=(3, 2, 2),
    )
    base_url = f"http://dm/artifacts/v1/dataset-builds/{artifacts.dataset_build_id}"
    responses = build_responses(artifacts, base_url)
    opener = MockOpener(responses)

    config = WorkerConfig(
        node_label="node-1",
        runtime_host="127.0.0.1",
        runtime_port=9000,
        cache_dir=str(tmp_path / "cache"),
    )
    worker = WorkerProcess(config, initialization_seed=42, opener=opener)

    mock_client = MagicMock()
    mock_client.expected_workers = 2
    mock_client.worker_id = 0
    mock_client.session_id = 100
    mock_client.attempt_id = "attempt-timing"
    worker._client = mock_client

    # Provision all shards
    assignment = DatasetAssignment.from_dict(
        {
            "dataset_build_id": artifacts.dataset_build_id,
            "dataset_manifest_hash": artifacts.dataset_manifest_hash,
            "shard_id": 0,
            "artifact_base_url": base_url,
            "root_manifest_path": "manifest.json",
            "expected_shard_count": 2,
            "profile": "CNN_IMAGE_CLASSIFICATION_V1",
            "cache_scope": "all_shards",
        }
    )
    worker._provision(assignment)
    return worker, mock_client, artifacts


def test_compute_timing_multi_unit(provisioned_worker):
    worker, mock_client, _artifacts = provisioned_worker

    # StepStart with 2 work units across shard 0 and shard 1
    step_msg = StepStart.from_dict(
        {
            "attempt_id": "attempt-timing",
            "epoch": 0,
            "step_id": 1,
            "batch_ordinal": 0,
            "model_version": 0,
            "shard_id": 0,
            "batch_id": 0,
            "expected_sample_count": 8,
            "training_strategy": "strict_bsp",
            "parameter_manifest_hash": worker.manifest_hash,
            "work_units": [
                {"shard_id": 0, "batch_id": 0, "sample_count": 4},
                {"shard_id": 1, "batch_id": 0, "sample_count": 4},
            ],
        }
    )

    worker._compute(step_msg, operation_id=1)

    mock_client.send_gradient.assert_called_once()
    kwargs = mock_client.send_gradient.call_args[1]

    assert "compute_ms" in kwargs
    assert isinstance(kwargs["compute_ms"], float)
    assert kwargs["compute_ms"] > 0.0
    assert kwargs["sample_count"] == 8
    assert kwargs["shard_id"] == 0
    assert kwargs["batch_id"] == 0


def test_compute_timing_legacy_step_start(provisioned_worker):
    worker, mock_client, _artifacts = provisioned_worker

    # Legacy StepStart without work_units field
    step_msg = StepStart.from_dict(
        {
            "attempt_id": "attempt-timing",
            "epoch": 0,
            "step_id": 2,
            "batch_ordinal": 1,
            "model_version": 0,
            "shard_id": 0,
            "batch_id": 1,
            "expected_sample_count": 4,
            "training_strategy": "strict_bsp",
            "parameter_manifest_hash": worker.manifest_hash,
        }
    )

    worker._compute(step_msg, operation_id=2)

    mock_client.send_gradient.assert_called_once()
    kwargs = mock_client.send_gradient.call_args[1]

    assert "compute_ms" in kwargs
    assert isinstance(kwargs["compute_ms"], float)
    assert kwargs["compute_ms"] > 0.0
    assert kwargs["sample_count"] == 4
