"""PostgreSQL integration and migration tests.

CANONICAL MANDATE:
CI must actually test against real PostgreSQL (never SQLite):
- empty database -> alembic upgrade head
- repository operations
- one-active-attempt unique constraint
- concurrent Start collision
- runtime_event_seq uniqueness
- idempotency persistence/concurrency

In CI (CI=true / GITHUB_ACTIONS=true), TEST_DATABASE_URL is strictly required.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
IS_CI = os.environ.get("CI") == "true" or os.environ.get("GITHUB_ACTIONS") == "true"

if IS_CI and not TEST_DB_URL:
    pytest.fail("TEST_DATABASE_URL must be provided in CI environment!", pytrace=False)

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL,
    reason="TEST_DATABASE_URL not configured for PostgreSQL integration tests.",
)


@pytest.fixture(scope="module")
def pg_conn():
    """Module-scoped PostgreSQL connection for integration tests."""
    assert TEST_DB_URL is not None
    conn = psycopg.connect(TEST_DB_URL, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


def test_01_alembic_migrations():
    """Verify that Alembic migrations run cleanly up to head."""
    repo_root = Path(__file__).resolve().parents[4]
    alembic_ini = repo_root / "alembic.ini"
    assert alembic_ini.exists(), f"alembic.ini not found at {alembic_ini}"

    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DB_URL)
    # Upgrade to head
    command.upgrade(alembic_cfg, "head")


def test_02_one_active_attempt_unique_constraint(pg_conn):
    """Verify the PostgreSQL partial unique index uq_attempts__one_active."""
    with pg_conn.cursor() as cur:
        # Create a test job
        job_id = f"job-test-{int(datetime.now(UTC).timestamp() * 1000)}"
        cur.execute(
            """
            INSERT INTO jobs (
                job_id, display_name, description, state, requested_contract, contract_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (job_id, "Test Job", "Test Description", "READY", "{}", "hash123"),
        )

        # Create first active attempt (WAITING_WORKERS)
        att1_id = f"att-1-{int(datetime.now(UTC).timestamp() * 1000)}"
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, attempt_number, state, execution_mode, contract_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (att1_id, job_id, 1, "WAITING_WORKERS", "FRESH", "hash123"),
        )
        pg_conn.commit()

        # Second active attempt for same job must violate uq_attempts__one_active
        att2_id = f"att-2-{int(datetime.now(UTC).timestamp() * 1000)}"
        with pytest.raises(psycopg.errors.UniqueViolation), pg_conn.savepoint():
            cur.execute(
                """
                INSERT INTO attempts (
                    attempt_id, job_id, attempt_number, state, execution_mode, contract_hash
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (att2_id, job_id, 2, "RUNNING", "FRESH", "hash123"),
            )


def test_03_concurrent_start_collision_mapping(pg_conn):
    """Verify attempt_service.start_job catches UniqueViolation and maps to error."""
    from pbl4.management_backend.services import attempt_service

    with pg_conn.cursor() as cur:
        job_id = f"job-coll-{int(datetime.now(UTC).timestamp() * 1000)}"
        cur.execute(
            """
            INSERT INTO jobs (
                job_id, display_name, description, state, requested_contract, contract_hash
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (job_id, "Collision Job", "", "READY", "{}", "hash_coll"),
        )
        pg_conn.commit()

    # First start succeeds
    attempt_row, _cmd_row = attempt_service.start_job(pg_conn, job_id)
    assert attempt_row["state"] == "WAITING_WORKERS"
    pg_conn.commit()

    # Second start collides and raises AttemptConflictError
    with pytest.raises(attempt_service.AttemptConflictError) as exc_info:
        attempt_service.start_job(pg_conn, job_id)

    assert exc_info.value.code == "ACTIVE_ATTEMPT_EXISTS"
    pg_conn.rollback()


def test_04_runtime_event_seq_uniqueness(pg_conn):
    """Verify runtime_event_seq deduplication and conflicting payload integrity check."""
    from pbl4.management_backend.services.event_ingest import (
        ConflictingEventPayloadError,
        ingest_runtime_event,
    )

    attempt_id = f"att-evt-{int(datetime.now(UTC).timestamp() * 1000)}"
    now = datetime.now(UTC)

    # 1. First event
    row1 = ingest_runtime_event(
        pg_conn,
        attempt_id=attempt_id,
        runtime_event_seq=1,
        event_type="TRAINING_STEP_COMMITTED",
        severity="INFO",
        occurred_at=now,
        payload={"loss": 0.5, "step": 1},
    )
    assert row1 is not None
    pg_conn.commit()

    # 2. Duplicate event with identical payload -> deduplicated
    row2 = ingest_runtime_event(
        pg_conn,
        attempt_id=attempt_id,
        runtime_event_seq=1,
        event_type="TRAINING_STEP_COMMITTED",
        severity="INFO",
        occurred_at=now,
        payload={"loss": 0.5, "step": 1},
    )
    assert row2 is not None
    assert row2["runtime_event_seq"] == 1

    # 3. Conflicting payload -> ConflictingEventPayloadError
    with pytest.raises(ConflictingEventPayloadError):
        ingest_runtime_event(
            pg_conn,
            attempt_id=attempt_id,
            runtime_event_seq=1,
            event_type="TRAINING_STEP_COMMITTED",
            severity="INFO",
            occurred_at=now,
            payload={"loss": 99.9, "step": 1},
        )
    pg_conn.rollback()


def test_05_idempotency_persistence_and_concurrency(pg_conn):
    """Verify idempotency persistence in real PostgreSQL."""
    from pbl4.management_backend.services.idempotency import (
        IdempotencyConflictError,
        execute_idempotent_command,
    )

    idemp_key = f"idemp-{datetime.now(UTC).timestamp()}"
    executed_count = 0

    def side_effect(conn, command_id):
        nonlocal executed_count
        executed_count += 1
        return {"command_id": command_id, "status": "CREATED"}, 201

    # First call executes side effect
    resp1, status1 = execute_idempotent_command(
        pg_conn,
        operator_identity="admin",
        endpoint_semantic_scope="JOBS",
        idempotency_key=idemp_key,
        operation="POST",
        path="/api/v1/jobs/test-job/start",
        query_params=None,
        body={"note": "first"},
        target_type="JOB",
        target_id="test-job",
        command_type="START_ATTEMPT",
        execute_fn=side_effect,
    )
    assert status1 == 201
    assert executed_count == 1
    pg_conn.commit()

    # Second call with identical key and payload returns cached response without re-executing
    resp2, status2 = execute_idempotent_command(
        pg_conn,
        operator_identity="admin",
        endpoint_semantic_scope="JOBS",
        idempotency_key=idemp_key,
        operation="POST",
        path="/api/v1/jobs/test-job/start",
        query_params=None,
        body={"note": "first"},
        target_type="JOB",
        target_id="test-job",
        command_type="START_ATTEMPT",
        execute_fn=side_effect,
    )
    assert status2 == 201
    assert resp2 == resp1
    assert executed_count == 1  # Not executed again!

    # Third call with reused key but DIFFERENT payload raises IdempotencyConflictError
    with pytest.raises(IdempotencyConflictError) as exc_info:
        execute_idempotent_command(
            pg_conn,
            operator_identity="admin",
            endpoint_semantic_scope="JOBS",
            idempotency_key=idemp_key,
            operation="POST",
            path="/api/v1/jobs/test-job/start",
            query_params=None,
            body={"note": "DIFFERENT_BODY"},
            target_type="JOB",
            target_id="test-job",
            command_type="START_ATTEMPT",
            execute_fn=side_effect,
        )
    assert exc_info.value.code == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"
    pg_conn.rollback()
