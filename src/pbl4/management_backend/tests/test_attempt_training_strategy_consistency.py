"""Unit tests verifying training strategy consistency and AttemptDataIntegrityError handling."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pbl4.management_backend.app import create_app
from pbl4.management_backend.repositories import attempt_repository
from pbl4.management_backend.services import attempt_service
from pbl4.management_backend.services.attempt_service import AttemptDataIntegrityError

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def app_client():
    from pbl4.management_backend import db
    from pbl4.management_backend.config import get_settings

    db.close_pool()
    settings = get_settings()
    with patch.object(settings, "database_url", None), patch.object(db, "init_pool"):
        db.close_pool()
        app = create_app()
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
        db.close_pool()


# ─── SQL Generation & Aliasing Tests ─────────────────────────────────────────


def test_list_attempts_sql_uses_left_join_and_table_aliases():
    """Verify list_attempts builds LEFT JOIN and aliases all filter/sort columns."""
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    attempt_repository.list_attempts(
        mock_conn,
        job_id="job_abc",
        state="CREATED",
        execution_mode="FRESH",
        limit=20,
    )

    assert mock_cur.execute.called
    sql, params = mock_cur.execute.call_args[0]

    # Verify LEFT JOIN and training_strategy projection
    assert "LEFT JOIN jobs j ON a.job_id = j.job_id" in sql
    expected_proj = (
        "j.resolved_contract->'synchronization'->>'training_strategy' AS training_strategy"
    )
    assert expected_proj in sql

    # Verify column aliasing in WHERE and ORDER BY
    assert "a.job_id = %s" in sql
    assert "a.state = %s" in sql
    assert "a.execution_mode = %s" in sql
    assert "ORDER BY a.created_at DESC, a.attempt_id DESC" in sql
    assert params == ["job_abc", "CREATED", "FRESH", 20]


def test_list_attempts_cursor_pagination_sql_aliasing():
    """Verify cursor conditions use aliased column references."""
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    cursor_dt = datetime.now(UTC)
    attempt_repository.list_attempts(
        mock_conn,
        cursor_dt=cursor_dt,
        cursor_id="att_123",
        limit=10,
    )

    sql, params = mock_cur.execute.call_args[0]
    assert "(a.created_at, a.attempt_id) < (%s, %s)" in sql
    assert params == [cursor_dt, "att_123", 10]


# ─── Malformed Contract & JSONDecodeError Tests ──────────────────────────────


def test_get_attempt_detail_catches_malformed_json_contract():
    """Verify that unparseable JSON string in resolved_contract raises AttemptDataIntegrityError."""
    mock_conn = MagicMock()
    with (
        patch.object(
            attempt_service.attempt_repository,
            "get_attempt",
            return_value={"attempt_id": "att_1", "job_id": "job_1"},
        ),
        patch.object(
            attempt_service.job_repository,
            "get_job",
            return_value={"job_id": "job_1", "resolved_contract": "{malformed_json: true,"},
        ),
    ):
        with pytest.raises(AttemptDataIntegrityError) as exc_info:
            attempt_service.get_attempt_detail(mock_conn, "att_1")

        assert "unparseable frozen resolved contract" in str(exc_info.value)


def test_api_attempt_detail_returns_500_data_integrity_error_on_corrupt_contract(app_client):
    """Verify HTTP endpoint maps AttemptDataIntegrityError to 500 DATA_INTEGRITY_ERROR."""
    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch(
            "pbl4.management_backend.services.attempt_service.get_attempt_detail",
            side_effect=AttemptDataIntegrityError("Corrupt contract"),
        ),
    ):
        r = app_client.get("/api/v1/attempts/att_corrupt")
        assert r.status_code == 500
        body = r.json()
        assert "error" in body
        assert body["error"]["code"] == "DATA_INTEGRITY_ERROR"
        assert "Corrupt contract" in body["error"]["message"]


# ─── API Consistency Test (List vs Detail) ───────────────────────────────────


def test_api_list_and_detail_return_consistent_training_strategy(app_client):
    """Verify both list and detail return identical training_strategy without runtime_metadata."""
    now = datetime.now(UTC)

    mock_attempt_row = {
        "attempt_id": "att_test_1",
        "job_id": "job_test_1",
        "state": "CREATED",
        "execution_mode": "FRESH",
        "contract_hash": "a" * 64,
        "runtime_metadata": None,  # Crucial: No runtime snapshot yet!
        "training_strategy": "strict_bsp",  # Provided by LEFT JOIN
        "created_at": now,
        "started_at": None,
        "ended_at": None,
        "failure_code": None,
    }

    mock_detail = {
        "row": mock_attempt_row,
        "job": {"job_id": "job_test_1"},
        "expected_workers": 3,
        "training_strategy": "strict_bsp",
        "workers": [],
        "snapshot": {},
    }

    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch(
            "pbl4.management_backend.services.attempt_service.list_attempts",
            return_value=[mock_attempt_row],
        ),
        patch(
            "pbl4.management_backend.services.attempt_service.get_attempt_detail",
            return_value=mock_detail,
        ),
    ):
        # 1. Test GET /api/v1/attempts
        res_list = app_client.get("/api/v1/attempts")
        assert res_list.status_code == 200
        list_data = res_list.json()["data"]
        assert len(list_data) == 1
        assert list_data[0]["training_strategy"] == "strict_bsp"

        # 2. Test GET /api/v1/attempts/att_test_1
        res_detail = app_client.get("/api/v1/attempts/att_test_1")
        assert res_detail.status_code == 200
        detail_data = res_detail.json()["data"]
        assert detail_data["training_strategy"] == "strict_bsp"

        # 3. Assert exact equality
        assert list_data[0]["training_strategy"] == detail_data["training_strategy"]
