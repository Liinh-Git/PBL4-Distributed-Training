"""Tests for Dataset Manager client paths, source resolution, and purge constraints."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import httpx
import pytest
from starlette.requests import Request

from pbl4.management_backend.app import create_app
from pbl4.management_backend.clients.dataset_manager import (
    DatasetManagerBusinessError,
    DatasetManagerClient,
    DatasetManagerUnavailableError,
)
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
        records.append(
            {
                "method": request.method,
                "url": str(request.url),
                "headers": dict(request.headers),
                "content": request.content.decode("utf-8") if request.content else "",
            }
        )
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
        command_id="cmd-456",
        idempotency_key="idemp-123",
        source={"type": "cifar10_download", "dataset_name": "cifar10"},
        batch_size=128,
        partition_seed=42,
        profile="default",
        input_shape=[3, 32, 32],
        normalization={"mean": [0.4914, 0.4822, 0.4465], "std": [0.2470, 0.2435, 0.2616]},
    )
    assert records[-1]["method"] == "POST"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds"
    assert records[-1]["headers"]["idempotency-key"] == "idemp-123"
    import json

    assert json.loads(records[-1]["content"])["command_id"] == "cmd-456"
    assert "dataset_build_id" not in json.loads(records[-1]["content"])

    # 2. get_build
    client.get_build("build-1")
    assert records[-1]["method"] == "GET"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1"

    # 3. rebuild
    client.rebuild(
        source_dataset_build_id="build-1",
        command_id="cmd-r",
        idempotency_key="idemp-r",
        batch_size=128,
        partition_seed=42,
    )
    assert records[-1]["method"] == "POST"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1/rebuild"
    assert records[-1]["headers"]["idempotency-key"] == "idemp-r"
    assert json.loads(records[-1]["content"])["command_id"] == "cmd-r"
    assert "new_dataset_build_id" not in json.loads(records[-1]["content"])

    # 4. deprecate
    client.deprecate("build-1")
    assert records[-1]["method"] == "POST"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1/deprecate"

    # 5. purge
    client.purge("build-1", command_id="cmd-purge")
    assert records[-1]["method"] == "POST"
    assert records[-1]["url"] == "http://mock-dm:8001/api/v1/dataset-builds/build-1/purge"

    # 6. registration_ack
    client.registration_ack(
        "build-1",
        dataset_manifest_hash="abc",
        registration_id="reg-1",
        catalog_persisted_at="2026-09-09T00:00:00Z",
    )
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


def test_dataset_manager_health_uses_healthz_and_rejects_404():
    paths = []

    def healthy_handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        return httpx.Response(200, json={"status": "ok"})

    healthy_client = DatasetManagerClient(
        base_url="http://mock-dm:8001", transport=httpx.MockTransport(healthy_handler)
    )
    assert healthy_client.check_health() == "healthy"
    assert paths == ["/healthz"]

    unavailable_client = DatasetManagerClient(
        base_url="http://mock-dm:8001",
        transport=httpx.MockTransport(lambda _request: httpx.Response(404)),
    )
    assert unavailable_client.check_health() == "degraded"


def test_purge_error_codes():
    state_err = DatasetBuildStateError("Build must be DEPRECATED or FAILED before delete.")
    assert state_err.code == "INVALID_STATE"
    assert "DEPRECATED or FAILED" in str(state_err)

    in_use_err = DatasetBuildInUseError("Build referenced by jobs.")
    assert in_use_err.code == "DATASET_BUILD_IN_USE"


def test_case_a_409_business_error():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            409,
            json={"error": {"code": "SOURCE_NOT_REACQUIRABLE", "message": "Source missing"}},
        )
    )
    client = DatasetManagerClient(base_url="http://mock-dm:8001", transport=transport)
    with pytest.raises(DatasetManagerBusinessError) as exc_info:
        client.create_build(
            command_id="cmd-1",
            idempotency_key="k-1",
            source={"type": "cifar10_download", "dataset_name": "cifar10"},
            profile="default",
            input_shape=[3, 32, 32],
            normalization={},
            batch_size=32,
            partition_seed=42,
        )
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "SOURCE_NOT_REACQUIRABLE"
    assert not isinstance(exc_info.value, DatasetManagerUnavailableError)


def test_case_b_429_queue_full():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            429,
            json={"error": {"code": "BUILD_QUEUE_FULL", "message": "Queue is full"}},
        )
    )
    client = DatasetManagerClient(base_url="http://mock-dm:8001", transport=transport)
    with pytest.raises(DatasetManagerBusinessError) as exc_info:
        client.create_build(
            command_id="cmd-2",
            idempotency_key="k-2",
            source={"type": "cifar10_download", "dataset_name": "cifar10"},
            profile="default",
            input_shape=[3, 32, 32],
            normalization={},
            batch_size=32,
            partition_seed=42,
        )
    assert exc_info.value.status_code == 429
    assert exc_info.value.code == "BUILD_QUEUE_FULL"
    assert not isinstance(exc_info.value, DatasetManagerUnavailableError)


def test_case_c_404_not_found():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            404,
            json={"error": {"code": "NOT_FOUND", "message": "Build not found"}},
        )
    )
    client = DatasetManagerClient(base_url="http://mock-dm:8001", transport=transport)
    assert client.get_build("b-nonexistent") is None

    with pytest.raises(DatasetManagerBusinessError) as exc_info:
        client.get_manifest("b-nonexistent")
    assert exc_info.value.status_code == 404
    assert not isinstance(exc_info.value, DatasetManagerUnavailableError)


def test_case_d_503_server_error():
    transport = httpx.MockTransport(lambda _req: httpx.Response(503, text="Service Unavailable"))
    client = DatasetManagerClient(base_url="http://mock-dm:8001", transport=transport)
    with pytest.raises(DatasetManagerUnavailableError):
        client.create_build(
            command_id="cmd-3",
            idempotency_key="k-3",
            source={"type": "cifar10_download", "dataset_name": "cifar10"},
            profile="default",
            input_shape=[3, 32, 32],
            normalization={},
            batch_size=32,
            partition_seed=42,
        )


def test_case_e_transport_timeout():
    def timeout_handler(_req: httpx.Request):
        raise httpx.ReadTimeout("Read timed out")

    client = DatasetManagerClient(
        base_url="http://mock-dm:8001", transport=httpx.MockTransport(timeout_handler)
    )
    with pytest.raises(DatasetManagerUnavailableError):
        client.create_build(
            command_id="cmd-4",
            idempotency_key="k-4",
            source={"type": "cifar10_download", "dataset_name": "cifar10"},
            profile="default",
            input_shape=[3, 32, 32],
            normalization={},
            batch_size=32,
            partition_seed=42,
        )


def test_case_f_malformed_4xx_body():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(400, text="<bad html>Not JSON</bad html>")
    )
    client = DatasetManagerClient(base_url="http://mock-dm:8001", transport=transport)
    with pytest.raises(DatasetManagerBusinessError) as exc_info:
        client.create_build(
            command_id="cmd-5",
            idempotency_key="k-5",
            source={"type": "cifar10_download", "dataset_name": "cifar10"},
            profile="default",
            input_shape=[3, 32, 32],
            normalization={},
            batch_size=32,
            partition_seed=42,
        )
    assert exc_info.value.status_code == 400
    assert not isinstance(exc_info.value, DatasetManagerUnavailableError)


def test_public_dm_409_is_not_503():
    """Prove that downstream DM 409 does NOT return public 503 DATASET_MANAGER_UNAVAILABLE."""
    app = create_app()
    req = MagicMock(spec=Request)
    req.headers = {}
    req.state = MagicMock()
    req.state.request_id = "req-123"

    handler = app.exception_handlers[DatasetManagerBusinessError]
    resp = asyncio.run(
        handler(
            req,
            DatasetManagerBusinessError(
                status_code=409,
                code="SOURCE_NOT_REACQUIRABLE",
                message="Source missing",
            ),
        )
    )
    assert resp.status_code == 409
    body = json.loads(resp.body)
    assert body["error"]["code"] == "SOURCE_NOT_REACQUIRABLE"
    assert body["error"]["code"] != "DATASET_MANAGER_UNAVAILABLE"
