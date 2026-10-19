"""Phase 2 tests — Backend Global Single-Active Attempt Invariant Enforcement.

Verifies:
1. Normal active attempt states (CREATED, WAITING_WORKERS, PROVISIONING, INITIALIZING, RUNNING)
   prevent subsequent launches across any job.
2. COMPLETING state is recognized as active by attempt_repository and get_active_attempt(),
   rejecting start/retry/resume via service check with HTTP 409 ACTIVE_ATTEMPT_EXISTS.
3. Active attempt belonging to Job A prevents launching Job B (global single-active invariant).
4. Real concurrent start requests under PostgreSQL race conditions: partial unique index
   uq_attempts__one_active enforces exactly one winner; loser gets ACTIVE_ATTEMPT_EXISTS;
   no orphan allocations or dirty state.
5. Other entry points (retry_job, resume_job) are equally protected against active attempts.
6. Unrelated database UniqueViolations (e.g. primary key collision) are NOT masked as ACTIVE_ATTEMPT_EXISTS.
7. FastAPI HTTP API contract maps AttemptConflictError to HTTP 409 ACTIVE_ATTEMPT_EXISTS for start, retry, and resume.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import psycopg
import pytest
from fastapi.testclient import TestClient

from pbl4.management_backend import db
from pbl4.management_backend.app import create_app
from pbl4.management_backend.repositories import attempt_repository, job_repository
from pbl4.management_backend.services import attempt_service
from pbl4.management_backend.services.attempt_service import (
    AttemptConflictError,
    _is_active_attempt_conflict,
)

TEST_DB_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or "postgresql://postgres:123456@localhost:5432/pbl4_test"
)


@pytest.fixture(scope="module", autouse=True)
def init_test_pool():
    db.init_pool(TEST_DB_URL, min_size=1, max_size=5)
    yield
    db.close_pool()


@pytest.fixture(scope="module")
def pg_conn():
    conn = psycopg.connect(TEST_DB_URL, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clean_db(pg_conn):
    """Ensure no leftover active attempts or uncommitted transactions between tests."""
    with suppress(Exception):
        pg_conn.rollback()
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE attempts
            SET state = 'FAILED'
            WHERE state IN (
                'CREATED', 'WAITING_WORKERS', 'PROVISIONING',
                'INITIALIZING', 'RUNNING', 'COMPLETING'
            )
            """
        )
    pg_conn.commit()
    yield
    with suppress(Exception):
        pg_conn.rollback()


def _create_ready_job(conn: psycopg.Connection, display_name: str = "Test Job") -> str:
    job_id = f"job-p2-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                job_id, display_name, description, state, requested_contract,
                resolved_contract, contract_hash, created_at, frozen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                display_name,
                "Phase 2 Test Description",
                "READY",
                json.dumps({}),
                json.dumps({
                    "synchronization": {"expected_workers": 2, "training_strategy": "strict_bsp"},
                    "training": {"training_seed": 42},
                    "model": {"model_id": "resnet18_groupnorm"},
                }),
                f"hash-{job_id}",
                now,
                now,
            ),
        )
        for i in range(2):
            node_id = f"node-p2-{job_id}-{i}"
            cur.execute(
                """
                INSERT INTO nodes (
                    node_id, display_name, credential_hash, credential_created_at,
                    capabilities_jsonb, enrolled_at, state
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (node_id) DO UPDATE SET state = 'ONLINE'
                """,
                (
                    node_id,
                    f"Node {i}",
                    "dummy_hash",
                    now,
                    "{}",
                    now,
                    "ONLINE",
                ),
            )
    conn.commit()
    return job_id


# ─── 1. Attempt active thông thường & COMPLETING ────────────────────────────


@pytest.mark.parametrize(
    "active_state",
    ["CREATED", "WAITING_WORKERS", "PROVISIONING", "INITIALIZING", "RUNNING", "COMPLETING"],
)
def test_active_attempt_states_prevent_start_job(pg_conn, active_state: str):
    """Verify that any active state (including COMPLETING) blocks new attempt start."""
    assert active_state in attempt_repository.ACTIVE_ATTEMPT_STATES
    job_id = _create_ready_job(pg_conn)
    attempt_id = f"att-act-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, state, execution_mode, contract_hash, created_at
            ) VALUES (%s, %s, %s, 'FRESH', %s, %s)
            """,
            (attempt_id, job_id, active_state, f"hash-{job_id}", now),
        )
    pg_conn.commit()

    # get_active_attempt must detect it
    active = attempt_repository.get_active_attempt(pg_conn)
    assert active is not None
    assert active["attempt_id"] == attempt_id
    assert active["state"] == active_state

    # start_job must reject before attempting creation
    with pytest.raises(AttemptConflictError) as exc_info:
        attempt_service.start_job(pg_conn, job_id)
    assert exc_info.value.code == "ACTIVE_ATTEMPT_EXISTS"
    assert attempt_id in str(exc_info.value)


def test_completing_state_lifecycle_transitions():
    """Verify state machine transitions regarding legacy COMPLETING state.

    COMPLETING is NOT part of ATTEMPT_STATE_PROGRESSION and RUNNING -> COMPLETING is rejected.
    Active attempts transition directly from RUNNING to COMPLETED (or FAILED/ABORTED).
    Legacy attempts in COMPLETING in the database can still transition to terminal states.
    """
    assert "COMPLETING" in attempt_repository.ACTIVE_ATTEMPT_STATES
    assert "COMPLETING" not in attempt_repository.ATTEMPT_STATE_PROGRESSION
    assert attempt_repository.ATTEMPT_STATE_PROGRESSION.get("COMPLETING") is None

    # RUNNING -> COMPLETING is strictly rejected
    assert attempt_repository.is_valid_attempt_transition("RUNNING", "COMPLETING") is False

    # RUNNING transitions directly to COMPLETED or other terminal states
    assert attempt_repository.is_valid_attempt_transition("RUNNING", "COMPLETED") is True
    assert attempt_repository.is_valid_attempt_transition("RUNNING", "FAILED") is True
    assert attempt_repository.is_valid_attempt_transition("RUNNING", "ABORTED") is True

    # Legacy rows in COMPLETING can only transition to terminal states
    assert attempt_repository.is_valid_attempt_transition("COMPLETING", "COMPLETED") is True
    assert attempt_repository.is_valid_attempt_transition("COMPLETING", "FAILED") is True
    assert attempt_repository.is_valid_attempt_transition("COMPLETING", "ABORTED") is True

    # Terminal -> COMPLETING is invalid
    assert attempt_repository.is_valid_attempt_transition("COMPLETED", "COMPLETING") is False
    # Backward transition COMPLETING -> RUNNING is invalid
    assert attempt_repository.is_valid_attempt_transition("COMPLETING", "RUNNING") is False


# ─── 2. Active Attempt thuộc Job khác (Global Invariant) ────────────────────


def test_cross_job_active_attempt_blocks_other_job(pg_conn):
    """When Job A has an active attempt, Job B must NOT be started."""
    job_a = _create_ready_job(pg_conn, display_name="Job A")
    job_b = _create_ready_job(pg_conn, display_name="Job B")

    # Start Job A
    att_a, _cmd_a = attempt_service.start_job(pg_conn, job_a)
    pg_conn.commit()

    # Job B start must be rejected
    with pytest.raises(AttemptConflictError) as exc_info:
        attempt_service.start_job(pg_conn, job_b)
    assert exc_info.value.code == "ACTIVE_ATTEMPT_EXISTS"
    assert att_a["attempt_id"] in str(exc_info.value)


# ─── 3. Request đồng thời (PostgreSQL Unique Index Race Condition) ──────────


def test_concurrent_starts_enforce_single_active_attempt(pg_conn):
    """Under genuine concurrency, uq_attempts__one_active allows exactly one winner."""
    job_1 = _create_ready_job(pg_conn, display_name="Concurrent Job 1")
    job_2 = _create_ready_job(pg_conn, display_name="Concurrent Job 2")

    barrier = threading.Barrier(2)

    def run_start(job_id: str) -> tuple[str, str]:
        with psycopg.connect(TEST_DB_URL) as conn:
            barrier.wait()
            try:
                att_row, _ = attempt_service.start_job(conn, job_id)
                conn.commit()
                return "created", att_row["attempt_id"]
            except AttemptConflictError as exc:
                conn.rollback()
                return exc.code, str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        f1 = executor.submit(run_start, job_1)
        f2 = executor.submit(run_start, job_2)
        results = [f1.result(), f2.result()]

    statuses = [r[0] for r in results]
    assert statuses.count("created") == 1, f"Expected exactly 1 created, got {statuses}"
    assert statuses.count("ACTIVE_ATTEMPT_EXISTS") == 1, f"Expected 1 ACTIVE_ATTEMPT_EXISTS, got {statuses}"

    # Verify exactly 1 active attempt in database
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM attempts
            WHERE state IN (
                'CREATED', 'WAITING_WORKERS', 'PROVISIONING',
                'INITIALIZING', 'RUNNING', 'COMPLETING'
            )
            """
        )
        count = cur.fetchone()[0]
        assert count == 1, f"Expected exactly 1 active attempt in DB, found {count}"


# ─── 4. Các entry point khác: retry_job & resume_job ────────────────────────


def test_retry_job_rejected_when_active_attempt_exists(pg_conn):
    """retry_job must be rejected when an active attempt exists globally."""
    job_1 = _create_ready_job(pg_conn, display_name="Retry Target Job")
    job_2 = _create_ready_job(pg_conn, display_name="Active Job")

    att_active, _ = attempt_service.start_job(pg_conn, job_2)
    pg_conn.commit()

    with pytest.raises(AttemptConflictError) as exc_info:
        attempt_service.retry_job(pg_conn, job_1)
    assert exc_info.value.code == "ACTIVE_ATTEMPT_EXISTS"
    assert att_active["attempt_id"] in str(exc_info.value)


def test_resume_job_rejected_when_active_attempt_exists(pg_conn):
    """resume_job must be rejected when an active attempt exists globally."""
    job_1 = _create_ready_job(pg_conn, display_name="Resume Target Job")
    job_2 = _create_ready_job(pg_conn, display_name="Active Job")

    job_1_row = job_repository.get_job(pg_conn, job_1)
    assert job_1_row is not None

    fake_ckpt = {
        "checkpoint_id": "ckpt-p2-test",
        "state": "COMPLETE",
        "contract_hash": job_1_row["contract_hash"],
        "created_by_attempt_id": "att-dummy",
        "model_sha256": "sha-model",
        "metadata_sha256": "sha-metadata",
        "dataset_build_id": None,
    }

    # Start job_2 to create active attempt
    att_active, _ = attempt_service.start_job(pg_conn, job_2)
    pg_conn.commit()

    with patch("pbl4.management_backend.services.attempt_service.checkpoint_repository.get_checkpoint", return_value=fake_ckpt):
        with pytest.raises(AttemptConflictError) as exc_info:
            attempt_service.resume_job(pg_conn, job_1, "ckpt-p2-test")
    assert exc_info.value.code == "ACTIVE_ATTEMPT_EXISTS"
    assert att_active["attempt_id"] in str(exc_info.value)


# ─── 5. Phân biệt UniqueViolation không liên quan ───────────────────────────


def test_unrelated_unique_violation_not_masked():
    """A UniqueViolation from another constraint (e.g. primary key) must NOT be masked."""

    class MockDiag:
        constraint_name = "attempts_pkey"

    class MockUniqueViolation(psycopg.errors.UniqueViolation):
        diag = MockDiag()

    exc = MockUniqueViolation("duplicate key value violates unique constraint 'attempts_pkey'")
    assert _is_active_attempt_conflict(exc) is False

    # Simulate start_job hitting an unrelated unique violation
    mock_conn = MagicMock()
    with patch("pbl4.management_backend.repositories.job_repository.get_job") as mock_get_job, \
         patch("pbl4.management_backend.repositories.attempt_repository.get_active_attempt", return_value=None), \
         patch("pbl4.management_backend.services.attempt_service._preflight_job_and_select_placements", return_value=[]), \
         patch("pbl4.management_backend.repositories.attempt_repository.create_attempt", side_effect=exc):

        mock_get_job.return_value = {
            "job_id": "job-test",
            "state": "READY",
            "contract_hash": "hash-123",
            "resolved_contract": {"synchronization": {"expected_workers": 2}},
        }

        # Must re-raise the original UniqueViolation, NOT AttemptConflictError
        with pytest.raises(psycopg.errors.UniqueViolation) as raised:
            attempt_service.start_job(mock_conn, "job-test")
        assert not isinstance(raised.value, AttemptConflictError)


# ─── 6. HTTP API Contract (FastAPI 409 ACTIVE_ATTEMPT_EXISTS) ───────────────


def test_api_start_job_returns_409_when_attempt_active():
    """POST /api/v1/jobs/{id}/start maps AttemptConflictError to HTTP 409 ACTIVE_ATTEMPT_EXISTS."""
    app = create_app()
    with patch("pbl4.management_backend.services.attempt_service.execute_start_job") as mock_start:
        mock_start.side_effect = AttemptConflictError(
            "Active attempt 'att-active-1' already running (V1: only one active at a time)."
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/jobs/job-test/start",
                headers={"Idempotency-Key": "ik-test-1"},
                json={},
            )
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "error" in body
            assert body["error"]["code"] == "ACTIVE_ATTEMPT_EXISTS"


def test_api_retry_job_returns_409_when_attempt_active():
    """POST /api/v1/jobs/{id}/retry maps AttemptConflictError to HTTP 409 ACTIVE_ATTEMPT_EXISTS."""
    app = create_app()
    with patch("pbl4.management_backend.services.attempt_service.execute_retry_job") as mock_retry:
        mock_retry.side_effect = AttemptConflictError(
            "Active attempt 'att-active-1' is running. Abort it before retrying."
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/jobs/job-test/retry",
                headers={"Idempotency-Key": "ik-test-2"},
            )
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "error" in body
            assert body["error"]["code"] == "ACTIVE_ATTEMPT_EXISTS"


def test_api_resume_job_returns_409_when_attempt_active():
    """POST /api/v1/jobs/{id}/resume maps AttemptConflictError to HTTP 409 ACTIVE_ATTEMPT_EXISTS."""
    app = create_app()
    with patch("pbl4.management_backend.services.attempt_service.execute_resume_job") as mock_resume:
        mock_resume.side_effect = AttemptConflictError(
            "Active attempt 'att-active-1' is running. Abort before resuming."
        )
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/api/v1/jobs/job-test/resume",
                headers={"Idempotency-Key": "ik-test-3"},
                json={"checkpoint_id": "ckpt-1"},
            )
            assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
            body = resp.json()
            assert "error" in body
            assert body["error"]["code"] == "ACTIVE_ATTEMPT_EXISTS"


def test_api_get_active_attempt_idle_and_active():
    """GET /api/v1/attempts/active returns data: null when idle, and ActiveAttemptResponse when active."""
    app = create_app()

    # Case 1: Idle cluster -> data is null
    with patch("pbl4.management_backend.db.get_connection"), \
         patch("pbl4.management_backend.services.attempt_service.get_global_active_attempt", return_value=None):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/attempts/active")
            assert resp.status_code == 200
            body = resp.json()
            assert "data" in body
            assert body["data"] is None

    # Case 2: Active cluster -> returns active attempt details and job_name
    active_row = {
        "attempt_id": "att-global-active-1",
        "job_id": "job-test-1",
        "job_name": "My Active Job",
        "state": "RUNNING",
        "execution_mode": "FRESH",
        "created_at": datetime.now(UTC),
        "started_at": datetime.now(UTC),
    }
    with patch("pbl4.management_backend.db.get_connection"), \
         patch("pbl4.management_backend.services.attempt_service.get_global_active_attempt", return_value=active_row):
        with TestClient(app, raise_server_exceptions=False) as client:
            resp = client.get("/api/v1/attempts/active")
            assert resp.status_code == 200
            body = resp.json()
            assert body["data"] is not None
            assert body["data"]["attempt_id"] == "att-global-active-1"
            assert body["data"]["job_id"] == "job-test-1"
            assert body["data"]["job_name"] == "My Active Job"
            assert body["data"]["state"] == "RUNNING"

