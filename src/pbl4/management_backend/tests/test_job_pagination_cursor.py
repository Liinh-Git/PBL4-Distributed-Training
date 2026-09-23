"""Unit tests verifying Job pagination, cursor encoding/decoding,
and repository architectural boundaries.
"""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from pbl4.management_backend.app import create_app
from pbl4.management_backend.repositories import job_repository
from pbl4.management_backend.services import job_service

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


# ─── 1. Architectural Boundary Test: Repository has NO Service Imports ─────


def test_job_repository_has_no_service_imports():
    """Verify job_repository.py strictly adheres to layered architecture.

    Repository must NEVER import from services (e.g. services.dataset_service).
    """
    repo_path = Path(job_repository.__file__).resolve()
    tree = ast.parse(repo_path.read_text(encoding="utf-8"), filename=str(repo_path))

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    service_imports = [
        m for m in imported_modules if "service" in m or "pbl4.management_backend.services" in m
    ]
    assert not service_imports, (
        f"job_repository.py violates layered architecture by importing services: {service_imports}"
    )


# ─── 2. Repository SQL & Filter Test ─────────────────────────────────────────


def test_job_repository_list_jobs_cursor_sql():
    """Verify job_repository.list_jobs generates correct SQL with cursor_dt & cursor_id."""
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    cursor_dt = datetime(2026, 9, 23, 12, 0, 0, tzinfo=UTC)
    cursor_id = "job_test_cursor_id"

    job_repository.list_jobs(
        mock_conn,
        state="READY",
        limit=25,
        cursor_dt=cursor_dt,
        cursor_id=cursor_id,
    )

    assert mock_cur.execute.called
    sql, params = mock_cur.execute.call_args[0]

    assert "(created_at, job_id) < (%s, %s)" in sql
    assert "state = %s" in sql
    assert params == ["READY", cursor_dt, cursor_id, 25]


# ─── 3. Service Cursor Decoding & Fallback Tests ─────────────────────────────


def test_job_service_list_jobs_decodes_canonical_base64_cursor():
    """Verify job_service decodes canonical opaque Base64 URL-safe JSON cursor."""
    mock_conn = MagicMock()
    dt = datetime(2026, 9, 23, 15, 30, 0, tzinfo=UTC)
    job_id = "job_canonical_123"

    canonical_cursor = job_service.encode_cursor(dt, job_id)

    with patch.object(job_service.job_repository, "list_jobs", return_value=[]) as mock_repo_list:
        job_service.list_jobs(mock_conn, cursor=canonical_cursor, limit=10)

        mock_repo_list.assert_called_once_with(
            mock_conn,
            state=None,
            dataset_build_id=None,
            q=None,
            limit=10,
            cursor_dt=dt,
            cursor_id=job_id,
        )


def test_job_service_list_jobs_decodes_legacy_pipe_cursor():
    """Verify job_service retains backward-compatibility with legacy 'timestamp|job_id' cursor."""
    mock_conn = MagicMock()
    dt = datetime(2026, 9, 23, 15, 30, 0, tzinfo=UTC)
    job_id = "job_legacy_456"

    legacy_cursor = f"{dt.isoformat()}|{job_id}"

    with patch.object(job_service.job_repository, "list_jobs", return_value=[]) as mock_repo_list:
        job_service.list_jobs(mock_conn, cursor=legacy_cursor, limit=10)

        mock_repo_list.assert_called_once_with(
            mock_conn,
            state=None,
            dataset_build_id=None,
            q=None,
            limit=10,
            cursor_dt=dt,
            cursor_id=job_id,
        )


def test_job_service_list_jobs_raises_invalid_cursor_on_garbage():
    """Verify job_service raises InvalidCursorError on malformed cursor string."""
    mock_conn = MagicMock()
    with pytest.raises(job_service.InvalidCursorError):
        job_service.list_jobs(mock_conn, cursor="malformed_cursor_not_valid_json_or_pipe")


# ─── 4. API Endpoint Integration Tests ───────────────────────────────────────


def test_api_list_jobs_emits_canonical_opaque_cursor(app_client):
    """Verify GET /api/v1/jobs emits canonical Base64 JSON cursor when has_more=True."""
    dt1 = datetime(2026, 9, 23, 10, 0, 0, tzinfo=UTC)
    dt2 = datetime(2026, 9, 23, 9, 0, 0, tzinfo=UTC)
    dt3 = datetime(2026, 9, 23, 8, 0, 0, tzinfo=UTC)

    mock_rows = [
        {
            "job_id": "job_1",
            "display_name": "Job 1",
            "state": "READY",
            "contract_hash": "hash1",
            "created_at": dt1,
            "attempt_count": 0,
            "latest_attempt_id": None,
            "latest_attempt_state": None,
        },
        {
            "job_id": "job_2",
            "display_name": "Job 2",
            "state": "READY",
            "contract_hash": "hash2",
            "created_at": dt2,
            "attempt_count": 1,
            "latest_attempt_id": "att_1",
            "latest_attempt_state": "COMPLETED",
        },
        {
            "job_id": "job_3",
            "display_name": "Job 3",
            "state": "DRAFT",
            "contract_hash": None,
            "created_at": dt3,
            "attempt_count": 0,
            "latest_attempt_id": None,
            "latest_attempt_state": None,
        },
    ]

    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch(
            "pbl4.management_backend.services.job_service.list_jobs",
            return_value=mock_rows,
        ),
    ):
        # Request limit=2: rows returned is 3, so has_more=True, last item in page is job_2
        res = app_client.get("/api/v1/jobs?limit=2")
        assert res.status_code == 200
        body = res.json()

        assert len(body["data"]) == 2
        next_cursor = body["page"]["next_cursor"]
        assert next_cursor is not None
        # Must not be plaintext pipe
        assert "|" not in next_cursor

        # Must decode to last item in page (job_2, dt2)
        decoded_dt, decoded_id = job_service.decode_cursor(next_cursor)
        assert decoded_dt == dt2
        assert decoded_id == "job_2"


def test_api_list_jobs_invalid_cursor_returns_400(app_client):
    """Verify GET /api/v1/jobs with invalid cursor returns HTTP 400 INVALID_CURSOR."""
    with patch("pbl4.management_backend.db.get_connection"):
        res = app_client.get("/api/v1/jobs?cursor=bad_cursor_content_!!!")
        assert res.status_code == 400
        body = res.json()
        assert "error" in body
        assert body["error"]["code"] == "INVALID_CURSOR"
