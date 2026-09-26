"""Smoke tests for Management Backend — no real DB required.

These tests use FastAPI TestClient and mock the DB connection pool
to verify routing, schemas, and business logic without a live PostgreSQL instance.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def client():
    from unittest.mock import patch

    from pbl4.management_backend import db
    from pbl4.management_backend.app import create_app
    from pbl4.management_backend.config import get_settings

    db.close_pool()
    settings = get_settings()
    with patch.object(settings, "database_url", None), patch.object(db, "init_pool"):
        db.close_pool()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        db.close_pool()


# ─── System Endpoints ─────────────────────────────────────────────────────────


def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    res = r.json()
    assert "data" in res and "meta" in res
    assert res["meta"]["request_id"].startswith("req_")
    data = res["data"]
    assert data["backend"] == "healthy"
    assert "postgres" in data
    assert "runtime_mcp" in data
    assert "dataset_manager" in data
    assert "timestamp" in data


def test_capabilities_ok(client):
    r = client.get("/api/v1/system/capabilities")
    assert r.status_code == 200
    res = r.json()
    assert "data" in res and "meta" in res
    assert res["meta"]["request_id"].startswith("req_")
    data = res["data"]
    assert data["api_version"] == "v1"
    assert "strict_bsp" in data["supported_training_strategies"]
    assert data["runtime_connected"] is False
    assert data["supported_models"] == [
        {
            "model_id": "resnet18_groupnorm",
            "display_name": "ResNet-18 (GroupNorm)",
            "task_type": "image_classification",
        }
    ]


def test_runtime_snapshot_ok(client):
    r = client.get("/api/v1/runtime/snapshot")
    assert r.status_code == 200
    res = r.json()
    assert "data" in res and "meta" in res
    assert res["meta"]["request_id"].startswith("req_")
    data = res["data"]
    assert data["stale"] is True


# ─── No-DB → 503 ──────────────────────────────────────────────────────────────


def test_list_datasets_without_db_returns_503(client):
    r = client.get("/api/v1/datasets")
    assert r.status_code == 503


def test_list_jobs_without_db_returns_503(client):
    r = client.get("/api/v1/jobs")
    assert r.status_code == 503


def test_list_attempts_without_db_returns_503(client):
    r = client.get("/api/v1/attempts")
    assert r.status_code == 503


def test_list_checkpoints_without_db_returns_503(client):
    r = client.get("/api/v1/checkpoints")
    assert r.status_code == 503


def test_list_events_without_db_returns_503(client):
    r = client.get("/api/v1/events")
    assert r.status_code == 503


def test_list_commands_without_db_returns_503(client):
    r = client.get("/api/v1/commands")
    assert r.status_code == 503


# ─── OpenAPI Schema ───────────────────────────────────────────────────────────


def test_openapi_schema_generated(client):
    r = client.get("/api/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert "paths" in schema
    # Verify key paths exist in the schema
    paths = schema["paths"]
    assert "/api/v1/health" in paths
    assert "/api/v1/jobs" in paths
    assert "/api/v1/datasets" in paths
    assert "/api/v1/attempts" in paths
    assert "/api/v1/checkpoints" in paths
    assert "/api/v1/commands" in paths
    assert "/api/v1/events" in paths
    assert "/api/v1/runtime/snapshot" in paths
    assert "/api/v1/system/capabilities" in paths


# ─── Unit: Job Service ────────────────────────────────────────────────────────


def test_validate_contract_missing_fields():
    from pbl4.management_backend.services.job_service import _validate_contract

    errors = _validate_contract({})
    assert len(errors) > 0
    # All required fields should be reported missing
    error_text = " ".join(errors)
    assert "dataset_build_id" in error_text


def test_validate_contract_unsupported_strategy():
    from pbl4.management_backend.services.job_service import _validate_contract

    errors = _validate_contract(
        {
            "dataset_build_id": "dsb_1",
            "model_id": "m1",
            "epochs": 5,
            "learning_rate": 0.01,
            "training_seed": 42,
            "training_strategy": "federated",  # unsupported
        }
    )
    assert any("strict_bsp" in e for e in errors)


def test_validate_contract_ok():
    from pbl4.management_backend.services.job_service import _validate_contract

    errors = _validate_contract(
        {
            "dataset_build_id": "dsb_1",
            "model_id": "m1",
            "epochs": 5,
            "learning_rate": 0.01,
            "training_seed": 42,
            "training_strategy": "strict_bsp",
        }
    )
    assert errors == []


def test_hash_contract_deterministic():
    from pbl4.common.hashing import canonical_json_hash
    from pbl4.management_backend.services.contract_resolver import hash_contract

    contract = {"a": 1, "b": [2, 3]}
    h1 = hash_contract(contract)
    h2 = canonical_json_hash(contract)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


# ─── Unit: Schemas ────────────────────────────────────────────────────────────


def test_health_response_schema():
    from pbl4.management_backend.schemas.runtime import HealthResponse

    now = datetime.now(UTC)
    resp = HealthResponse(
        backend="healthy",
        postgres="healthy",
        runtime_mcp="disconnected",
        dataset_manager="unknown",
        timestamp=now,
    )
    assert resp.backend == "healthy"


def test_job_create_request_schema():
    from pbl4.management_backend.schemas.job import JobCreateRequest

    req = JobCreateRequest(
        display_name="Test Job",
        requested_contract={
            "dataset_build_id": "dsb_1",
            "model_id": "m1",
            "epochs": 5,
            "learning_rate": 0.001,
            "training_seed": 42,
            "training_strategy": "strict_bsp",
        },
    )
    assert req.display_name == "Test Job"


def test_dataset_build_create_request_schema():
    from pbl4.management_backend.schemas.dataset import (
        DatasetBuildCreateRequest,
        PreprocessingConfig,
    )

    req = DatasetBuildCreateRequest(
        dataset_id="ds_1",
        profile="CNN_IMAGE_CLASSIFICATION_V1",
        batch_size=32,
        partition_seed=0,
        preprocessing=PreprocessingConfig(),
    )
    assert req.batch_size == 32


def test_dataset_create_rejects_unsupported_v1_capability():
    from pydantic import ValidationError

    from pbl4.management_backend.schemas.dataset import DatasetCreateRequest

    with pytest.raises(ValidationError):
        DatasetCreateRequest(
            name="unsupported",
            task_type="text_classification",
            source_type="local_directory",
            source_reference="/tmp/data",
        )


def test_openapi_documents_item_envelope(client):
    schema = client.get("/api/openapi.json").json()
    response_schema = schema["paths"]["/api/v1/jobs/{job_id}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    component = response_schema["$ref"].split("/")[-1]
    properties = schema["components"]["schemas"][component]["properties"]
    assert set(properties) == {"data", "meta"}


# ─── WebSocket Route Registered ───────────────────────────────────────────────


def test_websocket_route_registered(client):
    from fastapi.routing import APIWebSocketRoute

    app = client.app
    ws_routes = [r for r in app.routes if isinstance(r, APIWebSocketRoute)]
    assert any("/ws/v1/attempts/{attempt_id}" in r.path for r in ws_routes), (
        "WebSocket route /ws/v1/attempts/{attempt_id} not registered"
    )


# ─── Dataset Builds Error Handling Tests ─────────────────────────────────────


def test_list_dataset_builds_database_data_error_returns_500_without_leak(client):
    """Verify that psycopg.DataError during dataset builds query returns 500
    and does NOT leak DB internals."""
    from unittest.mock import patch

    import psycopg

    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch(
            "pbl4.management_backend.services.dataset_service.list_builds",
            side_effect=psycopg.DataError(
                "corrupted timestamp in table dataset_builds: 0000-00-00"
            ),
        ),
    ):
        res = client.get("/api/v1/dataset-builds")
        assert res.status_code == 500
        body = res.json()
        assert "error" in body
        assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
        assert body["error"]["message"] == "A database data processing error occurred."

        # Verify PostgreSQL internal details are NOT leaked to client
        details = body["error"].get("details")
        assert details is None or "db_error" not in details
        assert "corrupted timestamp" not in str(body)
        assert "dataset_builds" not in str(body)


def test_list_dataset_builds_invalid_cursor_returns_400_invalid_cursor(client):
    """Verify that a genuine client-side invalid cursor continues to return HTTP 400."""
    from unittest.mock import patch

    with patch("pbl4.management_backend.db.get_connection"):
        res = client.get("/api/v1/dataset-builds?cursor=invalid_base64_payload_!!!")
        assert res.status_code == 400
        body = res.json()
        assert "error" in body
        assert body["error"]["code"] == "INVALID_CURSOR"


# ─── Join Spec ps_host Advertising Tests ─────────────────────────────────────


def test_join_spec_advertises_dtp_host_when_runtime_advertised_host_set():
    """Verify join-spec advertises RUNTIME_ADVERTISED_HOST as ps_host for multi-machine clusters."""
    from unittest.mock import MagicMock, patch

    from pbl4.management_backend.config import BackendSettings
    from pbl4.management_backend.services import attempt_service

    mock_conn = MagicMock()
    mock_attempt = {
        "attempt_id": "att-spec-1",
        "job_id": "job-1",
        "contract_hash": "h" * 64,
        "state": "INITIALIZING",
    }
    mock_job = {
        "job_id": "job-1",
        "resolved_contract": {
            "synchronization": {"expected_workers": 3},
        },
    }
    custom_settings = BackendSettings(
        RUNTIME_HOST="127.0.0.1",
        RUNTIME_ADVERTISED_HOST="192.168.1.100",
        RUNTIME_PORT=9000,
    )

    mock_gw = MagicMock(connected=True)

    with (
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value=mock_attempt,
        ),
        patch("pbl4.management_backend.repositories.job_repository.get_job", return_value=mock_job),
        patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_gw),
        patch("pbl4.management_backend.config.get_settings", return_value=custom_settings),
    ):
        spec = attempt_service.get_join_spec(mock_conn, "att-spec-1")
        assert spec is not None
        assert spec["ps_host"] == "192.168.1.100"
        assert spec["ps_port"] == 9000
        assert spec["expected_workers"] == 3


def test_join_spec_falls_back_to_runtime_host_when_advertised_host_not_set():
    """Verify join-spec falls back to RUNTIME_HOST when RUNTIME_ADVERTISED_HOST is not set."""
    from unittest.mock import MagicMock, patch

    from pbl4.management_backend.config import BackendSettings
    from pbl4.management_backend.services import attempt_service

    mock_conn = MagicMock()
    mock_attempt = {
        "attempt_id": "att-spec-2",
        "job_id": "job-2",
        "contract_hash": "h" * 64,
        "state": "INITIALIZING",
    }
    mock_job = {
        "job_id": "job-2",
        "resolved_contract": {
            "synchronization": {"expected_workers": 3},
        },
    }
    default_settings = BackendSettings(
        RUNTIME_HOST="10.0.0.5",
        RUNTIME_ADVERTISED_HOST=None,
        RUNTIME_PORT=9000,
    )
    mock_gw = MagicMock(connected=True)

    with (
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value=mock_attempt,
        ),
        patch("pbl4.management_backend.repositories.job_repository.get_job", return_value=mock_job),
        patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_gw),
        patch("pbl4.management_backend.config.get_settings", return_value=default_settings),
    ):
        spec = attempt_service.get_join_spec(mock_conn, "att-spec-2")
        assert spec is not None
        assert spec["ps_host"] == "10.0.0.5"
        assert spec["ps_port"] == 9000


def test_get_step_detail_matches_contract(client):
    """Verify GET /api/v1/attempts/{attempt_id}/steps/{step_id} returns exact contract response."""
    from datetime import datetime
    from unittest.mock import patch

    mock_attempt = {"attempt_id": "attempt_demo_001", "state": "RUNNING"}
    mock_step = {
        "attempt_id": "attempt_demo_001",
        "training_strategy": "strict_bsp",
        "step_id": 17,
        "operation_id": 17,
        "input_model_version": 41,
        "output_model_version": 42,
        "state": "COMMITTED",
        "epoch": 2,
        "batch_ordinal": 5,
        "total_sample_count": 96,
        "started_at": datetime.fromisoformat("2026-09-07T03:24:10.000+00:00"),
        "update_completed_at": datetime.fromisoformat("2026-09-07T03:24:15.600+00:00"),
        "synchronization_completed_at": datetime.fromisoformat("2026-09-07T03:24:16.700+00:00"),
        "checkpoint_completed_at": datetime.fromisoformat("2026-09-07T03:24:17.800+00:00"),
        "committed_at": datetime.fromisoformat("2026-09-07T03:24:18.000+00:00"),
    }
    mock_worker_steps = [
        {
            "worker_id": 0,
            "session_id": 10000,
            "shard_id": 0,
            "batch_id": 105,
            "sample_count": 32,
            "contribution_accepted": True,
            "parameter_applied": True,
            "loss": 0.22,
            "accuracy": 88.5,
            "compute_ms": 65.4,
            "upload_ms": 28.1,
            "parameter_apply_ms": 12.0,
            "bytes_sent": 18240000,
            "bytes_received": 18240000,
        },
        {
            "worker_id": 1,
            "session_id": 10001,
            "shard_id": 1,
            "batch_id": 105,
            "sample_count": 32,
            "contribution_accepted": True,
            "parameter_applied": True,
            "loss": 0.22,
            "accuracy": 88.5,
            "compute_ms": 65.4,
            "upload_ms": 28.1,
            "parameter_apply_ms": 12.0,
            "bytes_sent": 18240000,
            "bytes_received": 18240000,
        },
        {
            "worker_id": 2,
            "session_id": 10002,
            "shard_id": 2,
            "batch_id": 105,
            "sample_count": 32,
            "contribution_accepted": True,
            "parameter_applied": True,
            "loss": 0.22,
            "accuracy": 88.5,
            "compute_ms": 65.4,
            "upload_ms": 28.1,
            "parameter_apply_ms": 12.0,
            "bytes_sent": 18240000,
            "bytes_received": 18240000,
        },
    ]

    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value=mock_attempt,
        ),
        patch(
            "pbl4.management_backend.repositories.step_repository.get_step",
            return_value=mock_step,
        ),
        patch(
            "pbl4.management_backend.repositories.step_repository.get_worker_steps",
            return_value=mock_worker_steps,
        ),
    ):
        r = client.get("/api/v1/attempts/attempt_demo_001/steps/17")
        assert r.status_code == 200
        res = r.json()
        assert "data" in res and "meta" in res
        data = res["data"]
        assert data["training_strategy"] == "strict_bsp"
        assert data["step_id"] == 17
        assert data["operation_id"] == 17
        assert data["input_model_version"] == 41
        assert data["output_model_version"] == 42
        assert data["state"] == "COMMITTED"
        assert data["epoch"] == 2
        assert data["batch_ordinal"] == 5
        assert data["total_sample_count"] == 96
        assert data["timing"]["started_at"] == "2026-09-07T03:24:10Z"
        assert data["timing"]["update_completed_at"] == "2026-09-07T03:24:15.600000Z"
        assert data["timing"]["synchronization_completed_at"] == "2026-09-07T03:24:16.700000Z"
        assert data["timing"]["checkpoint_completed_at"] == "2026-09-07T03:24:17.800000Z"
        assert data["timing"]["committed_at"] == "2026-09-07T03:24:18Z"
        assert data["metrics"] == {"loss": 0.22, "accuracy": 88.5}
        assert len(data["worker_steps"]) == 3
        ws0 = data["worker_steps"][0]
        assert ws0["worker_id"] == 0
        assert ws0["session_id"] == "10000"
        assert ws0["shard_id"] == 0
        assert ws0["batch_id"] == 105
        assert ws0["sample_count"] == 32
        assert ws0["contribution_accepted"] is True
        assert ws0["parameter_applied"] is True
        assert ws0["loss"] == 0.22
        assert ws0["accuracy"] == 88.5
        assert ws0["compute_ms"] == 65.4
        assert ws0["upload_ms"] == 28.1
        assert ws0["parameter_apply_ms"] == 12.0
        assert ws0["bytes_sent"] == 18240000
        assert ws0["bytes_received"] == 18240000


def test_get_system_capabilities_matches_contract(client):
    from unittest.mock import MagicMock, patch

    mock_gateway = MagicMock()
    mock_gateway.connected = True
    mock_gateway.runtime_instance_id = "runtime_machine_a_001"

    with patch("pbl4.management_backend.api.system.get_gateway", return_value=mock_gateway):
        r = client.get("/api/v1/system/capabilities")
        assert r.status_code == 200
        res = r.json()
        assert "data" in res and "meta" in res
        data = res["data"]
        assert data["api_version"] == "v1"
        assert data["dtp_versions"] == [1]
        assert data["mcp_versions"] == [1]
        assert data["runtime_connected"] is True
        assert data["runtime_instance_id"] == "runtime_machine_a_001"
        assert data["supported_training_strategies"] == ["strict_bsp"]
        assert data["feature_flags"] == {
            "attempt_websocket_stream": True,
            "manual_checkpoint_request": True,
        }
        assert isinstance(data["supported_models"], list)
        assert len(data["supported_models"]) >= 1
        assert "model_id" in data["supported_models"][0]
        assert "display_name" in data["supported_models"][0]
        assert "task_type" in data["supported_models"][0]

