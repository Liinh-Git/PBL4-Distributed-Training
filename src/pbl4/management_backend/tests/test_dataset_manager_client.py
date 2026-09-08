"""Tests for Dataset Manager client paths, source resolution, and purge constraints."""

from __future__ import annotations

import httpx
import pytest

from pbl4.management_backend.clients.dataset_manager import DatasetManagerClient
from pbl4.management_backend.services.dataset_service import (
    DatasetBuildInUseError,
    DatasetBuildStateError,
    resolve_dataset_manager_source,
)


def test_resolve_dataset_manager_source():
    # CIFAR-10 V1 resolution
    src = resolve_dataset_manager_source("builtin", "cifar10")
    assert src == {
        "type": "cifar10_download",
        "dataset_name": "cifar10",
    }

    # Unsupported combinations
    with pytest.raises(ValueError, match="Unsupported dataset source mapping"):
        resolve_dataset_manager_source("builtin", "imagenet")

    with pytest.raises(ValueError, match="Unsupported dataset source mapping"):
        resolve_dataset_manager_source("custom_s3", "my-bucket")


def test_dataset_manager_client_internal_paths():
    records = []

    def handler(request: httpx.Request) -> httpx.Response:
        records.append({
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "content": request.content.decode("utf-8") if request.content else "",
        })
        if request.url.path.endswith("/manifest.json"):
            return httpx.Response(
                200,
                json={"dataset_name": "cifar10", "manifest_hash": "abc", "total_samples": 50000},
            )
        return httpx.Response(200, json={"status": "ok"})

    transport = httpx.MockTransport(handler)
    client = DatasetManagerClient(base_url="http://mock-dm:8001", transport=transport)

    # 1. create_build
    client.create_build(
        dataset_build_id="build-1",
        command_id="cmd-456",
        idempotency_key="idemp-123",
        source={"type": "cifar10_download", "dataset_name": "cifar10"},
        batch_size=128,
        partition_seed=42,
        profile="default",
    )
    assert records[-1]["method"] == "POST"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds"
    assert records[-1]["headers"]["idempotency-key"] == "idemp-123"
    import json
    assert json.loads(records[-1]["content"])["command_id"] == "cmd-456"

    # 2. get_build
    client.get_build("build-1")
    assert records[-1]["method"] == "GET"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1"

    # 3. rebuild
    client.rebuild(
        source_dataset_build_id="build-1",
        new_dataset_build_id="build-2",
        command_id="cmd-r",
        idempotency_key="idemp-r",
        batch_size=128,
        partition_seed=42,
    )
    assert records[-1]["method"] == "POST"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1/rebuild"
    assert records[-1]["headers"]["idempotency-key"] == "idemp-r"
    assert json.loads(records[-1]["content"])["command_id"] == "cmd-r"

    # 4. deprecate
    client.deprecate("build-1")
    assert records[-1]["method"] == "POST"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1/deprecate"

    # 5. purge
    client.purge("build-1")
    assert records[-1]["method"] == "POST"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1/purge"

    # 6. registration_ack
    client.registration_ack("build-1", {"status": "ACK"})
    assert records[-1]["method"] == "POST"
    assert (
        records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1/registration-ack"
    )

    # 7. get_manifest artifact
    manifest, _ = client.get_manifest("build-1")
    assert records[-1]["method"] == "GET"
    assert (
        records[-1]["url"]
        == "http://mock-dm:8001/artifacts/v1/dataset-builds/build-1/manifest.json"
    )
    assert manifest["dataset_name"] == "cifar10"


def test_purge_error_codes():
    state_err = DatasetBuildStateError("Build must be DEPRECATED or FAILED before delete.")
    assert state_err.code == "INVALID_STATE"
    assert "DEPRECATED or FAILED" in str(state_err)

    in_use_err = DatasetBuildInUseError("Build referenced by jobs.")
    assert in_use_err.code == "DATASET_BUILD_IN_USE"
