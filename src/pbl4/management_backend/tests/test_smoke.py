"""Smoke tests for Management Backend — no real DB required.

These tests use FastAPI TestClient and mock the DB connection pool
to verify routing, schemas, and business logic without a live PostgreSQL instance.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    from management_backend.app import create_app
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ─── System Endpoints ─────────────────────────────────────────────────────────

def test_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    data = r.json()
    assert data["backend"] == "healthy"
    assert "postgres" in data
    assert "runtime_mcp" in data
    assert "timestamp" in data


def test_capabilities_ok(client):
    r = client.get("/api/v1/system/capabilities")
    assert r.status_code == 200
    data = r.json()
    assert data["api_version"] == "v1"
    assert "strict_bsp" in data["supported_training_strategies"]
    assert data["runtime_connected"] is False


def test_runtime_snapshot_ok(client):
    r = client.get("/api/v1/runtime/snapshot")
    assert r.status_code == 200
    data = r.json()
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
    from management_backend.services.job_service import _validate_contract
    errors = _validate_contract({})
    assert len(errors) > 0
    # All required fields should be reported missing
    error_text = " ".join(errors)
    assert "dataset_build_id" in error_text


def test_validate_contract_unsupported_strategy():
    from management_backend.services.job_service import _validate_contract
    errors = _validate_contract({
        "dataset_build_id": "dsb_1",
        "model_id": "m1",
        "epochs": 5,
        "learning_rate": 0.01,
        "training_seed": 42,
        "training_strategy": "federated",  # unsupported
    })
    assert any("strict_bsp" in e for e in errors)


def test_validate_contract_ok():
    from management_backend.services.job_service import _validate_contract
    errors = _validate_contract({
        "dataset_build_id": "dsb_1",
        "model_id": "m1",
        "epochs": 5,
        "learning_rate": 0.01,
        "training_seed": 42,
        "training_strategy": "strict_bsp",
    })
    assert errors == []


def test_hash_contract_deterministic():
    from management_backend.services.job_service import _hash_contract
    contract = {"a": 1, "b": [2, 3]}
    h1 = _hash_contract(contract)
    h2 = _hash_contract(contract)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


# ─── Unit: Schemas ────────────────────────────────────────────────────────────

def test_health_response_schema():
    from management_backend.schemas.runtime import HealthResponse
    now = datetime.now(timezone.utc)
    resp = HealthResponse(
        backend="healthy",
        postgres="healthy",
        runtime_mcp="disconnected",
        dataset_manager="unknown",
        timestamp=now,
    )
    assert resp.backend == "healthy"


def test_job_create_request_schema():
    from management_backend.schemas.job import JobCreateRequest
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
    from management_backend.schemas.dataset import DatasetBuildCreateRequest, PreprocessingConfig
    req = DatasetBuildCreateRequest(
        dataset_id="ds_1",
        profile="CIFAR10_STANDARD",
        batch_size=32,
        partition_seed=0,
        preprocessing=PreprocessingConfig(),
    )
    assert req.batch_size == 32


# ─── WebSocket Route Registered ───────────────────────────────────────────────

def test_websocket_route_registered(client):
    from fastapi.routing import APIWebSocketRoute
    app = client.app
    ws_routes = [r for r in app.routes if isinstance(r, APIWebSocketRoute)]
    assert any("/ws/v1/attempts/{attempt_id}" in r.path for r in ws_routes), \
        "WebSocket route /ws/v1/attempts/{attempt_id} not registered"
