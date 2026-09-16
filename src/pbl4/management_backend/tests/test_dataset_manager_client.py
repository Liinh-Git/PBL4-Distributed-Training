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
    DatasetManagerProtocolError,
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
        return httpx.Response(
            200,
            json={"request_id": "req-1", "data": {"status": "ok"}, "error": None},
        )

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


def test_control_response_envelope_is_unwrapped_once_at_client_boundary():
    payload = {"dataset_build_id": "build-1", "state": "CREATED"}
    client = DatasetManagerClient(
        base_url="http://mock-dm:8001",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                201,
                json={"request_id": "req-1", "data": payload, "error": None},
            )
        ),
    )
    assert (
        client.create_build(
            command_id="cmd-1",
            idempotency_key="key-1",
            source={"type": "cifar10_download", "dataset_name": "cifar10"},
            profile="CNN_IMAGE_CLASSIFICATION_V1",
            input_shape=[3, 32, 32],
            normalization={"mean": [0.0, 0.0, 0.0], "std": [1.0, 1.0, 1.0]},
            batch_size=32,
            partition_seed=42,
        )
        == payload
    )


def test_success_with_structured_error_maps_to_business_error():
    client = DatasetManagerClient(
        base_url="http://mock-dm:8001",
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "request_id": "req-1",
                    "data": None,
                    "error": {
                        "code": "BUILD_REJECTED",
                        "message": "Build rejected",
                        "details": {},
                        "retryable": False,
                    },
                },
            )
        ),
    )
    with pytest.raises(DatasetManagerBusinessError, match="BUILD_REJECTED"):
        client.get_build("build-1")


@pytest.mark.parametrize(
    "body",
    [
        {"dataset_build_id": "build-1"},
        {"request_id": "req-1", "data": {}, "error": None, "extra": True},
        {"request_id": "", "data": {}, "error": None},
    ],
)
def test_malformed_control_envelope_is_protocol_failure(body):
    client = DatasetManagerClient(
        base_url="http://mock-dm:8001",
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json=body)),
    )
    with pytest.raises(DatasetManagerProtocolError):
        client.get_build("build-1")


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


# ─── Configurable Timeout & Idempotency Tests ────────────────────────────────


def test_backend_settings_dataset_manager_timeout():
    """BackendSettings has default dataset_manager_timeout_seconds configured."""
    from pbl4.management_backend.config import BackendSettings

    settings = BackendSettings()
    assert settings.dataset_manager_timeout_seconds == 30.0


def test_init_client_wires_timeout_from_settings():
    """init_client receives timeout from settings and configures DatasetManagerClient."""
    from pbl4.management_backend.clients.dataset_manager import get_client, init_client

    client = init_client(base_url="http://127.0.0.1:9200", timeout=45.0)
    assert client._timeout == 45.0
    assert get_client()._timeout == 45.0
    assert client.available is True


def test_create_build_slow_dataset_manager_within_configured_timeout():
    """create_build succeeds with slow Dataset Manager within configured timeout."""
    import time
    from pbl4.management_backend.clients.dataset_manager import DatasetManagerClient

    def slow_handler(request: httpx.Request) -> httpx.Response:
        time.sleep(0.05)
        return httpx.Response(
            202,
            json={"request_id": "req-slow", "data": {"dataset_build_id": "build-slow", "state": "CREATED"}, "error": None},
        )

    client = DatasetManagerClient(
        base_url="http://mock-dm:8001",
        timeout=30.0,
        transport=httpx.MockTransport(slow_handler),
    )
    result = client.create_build(
        command_id="cmd-slow",
        idempotency_key="key-slow",
        source={"type": "cifar10_download", "dataset_name": "cifar10"},
        profile="CNN_IMAGE_CLASSIFICATION_V1",
        input_shape=[3, 32, 32],
        normalization={"mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]},
        batch_size=128,
        partition_seed=42,
    )
    assert result["dataset_build_id"] == "build-slow"
    assert result["state"] == "CREATED"


def test_create_build_timeout_enforcement_raises_unavailable():
    """create_build truthful failure when transport times out."""
    from pbl4.management_backend.clients.dataset_manager import (
        DatasetManagerClient,
        DatasetManagerUnavailableError,
    )

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("The read operation timed out")

    client = DatasetManagerClient(
        base_url="http://mock-dm:8001",
        timeout=30.0,
        transport=httpx.MockTransport(timeout_handler),
    )
    with pytest.raises(DatasetManagerUnavailableError, match="timed out"):
        client.create_build(
            command_id="cmd-to",
            idempotency_key="key-to",
            source={"type": "cifar10_download", "dataset_name": "cifar10"},
            profile="CNN_IMAGE_CLASSIFICATION_V1",
            input_shape=[3, 32, 32],
            normalization={"mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]},
            batch_size=128,
            partition_seed=42,
        )


def test_idempotency_timeout_and_retry_flow_preserves_command_and_single_build(monkeypatch):
    """Verify canonical 2-phase idempotency: timeout keeps command PENDING; retry reuses command_id."""
    from pbl4.management_backend.clients.dataset_manager import (
        DatasetManagerUnavailableError,
    )
    import pbl4.management_backend.services.dataset_service as ds_mod

    created_commands = []
    updated_command_states = []
    completed_idempotencies = []
    dispatched_failures = []
    persisted_builds = []

    # Mock repositories
    fake_conn = object()

    class FakeDB:
        @staticmethod
        def transaction():
            from contextlib import nullcontext
            return nullcontext(fake_conn)

    # Idempotency state
    idemp_state = {"action": "NEW", "cached_record": None}

    def mock_acquire(*args, **kwargs):
        return idemp_state["cached_record"], idemp_state["action"]

    def mock_dispatch_failure(conn, endpoint_semantic_scope, idempotency_key, command_id):
        dispatched_failures.append({"idempotency_key": idempotency_key, "command_id": command_id})
        # After dispatch failure, next attempt will RESUME
        idemp_state["action"] = "RESUME"
        idemp_state["cached_record"] = {"command_id": command_id, "status": "DISPATCH_FAILED"}

    def mock_complete(conn, **kwargs):
        completed_idempotencies.append(kwargs)

    def mock_get_dataset(conn, dataset_id):
        return {"source_type": "builtin", "source_reference": "cifar10"}

    def mock_create_command(conn, command_id, **kwargs):
        created_commands.append({"command_id": command_id, **kwargs})
        return {"command_id": command_id, "state": "PENDING"}

    def mock_get_command(conn, command_id):
        return {"command_id": command_id, "state": "PENDING"}

    def mock_update_command_state(conn, command_id, new_state, **kwargs):
        updated_command_states.append({"command_id": command_id, "state": new_state, **kwargs})
        return {"command_id": command_id, "state": new_state}

    def mock_create_build(conn, dataset_build_id, **kwargs):
        persisted_builds.append({"dataset_build_id": dataset_build_id, **kwargs})
        return {"dataset_build_id": dataset_build_id}

    def mock_get_build(conn, dataset_build_id):
        for b in persisted_builds:
            if b["dataset_build_id"] == dataset_build_id:
                return b
        return None

    monkeypatch.setattr(ds_mod.idempotency, "acquire_or_get_record", mock_acquire)
    monkeypatch.setattr(ds_mod.idempotency, "record_dispatch_failure", mock_dispatch_failure)
    monkeypatch.setattr(ds_mod.idempotency, "complete_record", mock_complete)
    monkeypatch.setattr(ds_mod.dataset_repository, "get_dataset", mock_get_dataset)
    monkeypatch.setattr(ds_mod.command_repository, "create_command", mock_create_command)
    monkeypatch.setattr(ds_mod.command_repository, "get_command", mock_get_command)
    monkeypatch.setattr(ds_mod.command_repository, "update_command_state", mock_update_command_state)
    monkeypatch.setattr(ds_mod.dataset_build_repository, "create_build", mock_create_build)
    monkeypatch.setattr(ds_mod.dataset_build_repository, "get_build", mock_get_build)

    call_count = 0

    def mock_dm_create_build(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise DatasetManagerUnavailableError("The read operation timed out")
        return {"dataset_build_id": "build-authoritative-999", "state": "CREATED"}

    mock_client = MagicMock()
    mock_client.create_build.side_effect = mock_dm_create_build
    monkeypatch.setattr(ds_mod, "get_client", lambda: mock_client)

    # 1. First attempt: times out
    with pytest.raises(DatasetManagerUnavailableError, match="timed out"):
        ds_mod.execute_create_build(
            FakeDB,
            dataset_id="ds_test",
            profile="CNN_IMAGE_CLASSIFICATION_V1",
            batch_size=256,
            partition_seed=2026,
            idempotency_key="idemp-canonical-1",
        )

    assert len(created_commands) == 1
    first_cmd_id = created_commands[0]["command_id"]
    assert len(dispatched_failures) == 1
    assert dispatched_failures[0]["command_id"] == first_cmd_id
    assert len(persisted_builds) == 0  # No build created yet

    # 2. Second attempt: same idempotency key and same body
    build_row, cmd_row = ds_mod.execute_create_build(
        FakeDB,
        dataset_id="ds_test",
        profile="CNN_IMAGE_CLASSIFICATION_V1",
        batch_size=256,
        partition_seed=2026,
        idempotency_key="idemp-canonical-1",
    )

    # Must reuse the same command_id!
    assert len(created_commands) == 1  # No new command created
    assert len(persisted_builds) == 1  # Exactly ONE build created
    assert persisted_builds[0]["dataset_build_id"] == "build-authoritative-999"
    assert updated_command_states[0]["target_id"] == "build-authoritative-999"
    assert completed_idempotencies[0]["command_id"] == first_cmd_id
    assert len(updated_command_states) == 1
    assert updated_command_states[0]["command_id"] == first_cmd_id
    assert updated_command_states[0]["state"] == "ACCEPTED"
    assert len(completed_idempotencies) == 1
