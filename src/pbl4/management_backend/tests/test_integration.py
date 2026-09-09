"""PostgreSQL integration and migration tests.

CANONICAL MANDATE:
CI and integration suites must actually test against real PostgreSQL (never SQLite):
- empty database -> alembic upgrade head
- one-active-Attempt race / partial unique constraint
- event sequence deduplication and conflict detection
- idempotency persistence and concurrency
- command durability through downstream failures
- dataset registration verification transaction

Final gate: 0 critical integration tests skipped!
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import quote

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import sql

TEST_DB_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:123456@localhost:5432/pbl4_test"
)


@pytest.fixture(scope="module", autouse=True)
def init_test_db_pool():
    """Initialize DB connection pool for service integration tests."""
    from pbl4.management_backend import db

    db.init_pool(TEST_DB_URL, min_size=1, max_size=5)
    yield
    db.close_pool()


@pytest.fixture(scope="module")
def pg_conn():
    """Module-scoped PostgreSQL connection for integration tests."""
    conn = psycopg.connect(TEST_DB_URL, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clean_db(pg_conn, request):
    """Ensure no leftover active attempts or uncommitted transactions between tests."""
    with suppress(Exception):
        pg_conn.rollback()
    if request.node.name == "test_01_alembic_migrations":
        yield
        return
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


def test_01_alembic_migrations():
    """Verify that Alembic migrations run cleanly up to head on real PostgreSQL."""
    repo_root = Path(__file__).resolve().parents[4]
    alembic_ini = repo_root / "alembic.ini"
    assert alembic_ini.exists(), f"alembic.ini not found at {alembic_ini}"

    schema_name = f"pbl4_migration_test_{uuid.uuid4().hex}"
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
    separator = "&" if "?" in TEST_DB_URL else "?"
    schema_url = f"{TEST_DB_URL}{separator}options={quote(f'-csearch_path={schema_name}')}"
    try:
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("sqlalchemy.url", schema_url.replace("%", "%%"))
        command.upgrade(alembic_cfg, "head")
        with psycopg.connect(schema_url) as conn:
            row = conn.execute("SELECT to_regclass('attempts')").fetchone()
            assert row == ("attempts",)
    finally:
        with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))


def test_02_one_active_attempt_unique_constraint(pg_conn):
    """Verify the PostgreSQL partial unique index uq_attempts__one_active."""
    with pg_conn.cursor() as cur:
        job_id = f"job-test-{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        cur.execute(
            """
            INSERT INTO jobs (
                job_id, display_name, description, state, requested_contract,
                resolved_contract, contract_hash, created_at, frozen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                "Test Job",
                "Description",
                "READY",
                json.dumps({"dataset_build_id": "bld-1"}),
                json.dumps({"synchronization": {"expected_workers": 3}}),
                "hash123",
                now,
                now,
            ),
        )

        # First active attempt (state = 'CREATED')
        att1_id = f"att-1-{uuid.uuid4().hex[:8]}"
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, state, execution_mode, contract_hash, created_at
            ) VALUES (%s, %s, 'CREATED', 'FRESH', 'hash123', %s)
            """,
            (att1_id, job_id, now),
        )
        pg_conn.commit()

        # Second active attempt for same job must violate uq_attempts__one_active
        att2_id = f"att-2-{uuid.uuid4().hex[:8]}"
        with pytest.raises(psycopg.errors.UniqueViolation), pg_conn.transaction():
            cur.execute(
                """
                INSERT INTO attempts (
                    attempt_id, job_id, state, execution_mode, contract_hash, created_at
                ) VALUES (%s, %s, 'RUNNING', 'FRESH', 'hash123', %s)
                """,
                (att2_id, job_id, now),
            )

        # Terminal state on attempt 1 allows subsequent attempt creation
        cur.execute(
            "UPDATE attempts SET state = 'COMPLETED', ended_at = %s WHERE attempt_id = %s",
            (now, att1_id),
        )
        pg_conn.commit()

        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, state, execution_mode, contract_hash, created_at
            ) VALUES (%s, %s, 'CREATED', 'FRESH', 'hash123', %s)
            """,
            (att2_id, job_id, now),
        )
        pg_conn.commit()


def test_03_concurrent_start_collision_mapping(pg_conn):
    """Verify attempt_service.start_job catches UniqueViolation and maps to AttemptConflictError."""
    from pbl4.management_backend.services import attempt_service

    with pg_conn.cursor() as cur:
        job_id = f"job-coll-{uuid.uuid4().hex[:8]}"
        now = datetime.now(UTC)
        cur.execute(
            """
            INSERT INTO jobs (
                job_id, display_name, description, state, requested_contract,
                resolved_contract, contract_hash, created_at, frozen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                job_id,
                "Collision Job",
                "",
                "READY",
                json.dumps({"dataset_build_id": "bld-1"}),
                json.dumps({"synchronization": {"expected_workers": 3}}),
                "hash_coll",
                now,
                now,
            ),
        )
        pg_conn.commit()

    barrier = threading.Barrier(2)

    def start_once() -> tuple[str, str]:
        with psycopg.connect(TEST_DB_URL) as conn:
            barrier.wait()
            try:
                attempt_row, _cmd_row = attempt_service.start_job(conn, job_id)
                conn.commit()
                return "created", attempt_row["attempt_id"]
            except attempt_service.AttemptConflictError as exc:
                conn.rollback()
                return exc.code, ""

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: start_once(), range(2)))

    assert [result[0] for result in results].count("created") == 1
    assert [result[0] for result in results].count("ACTIVE_ATTEMPT_EXISTS") == 1


def test_04_runtime_event_seq_uniqueness(pg_conn):
    """Verify runtime_event_seq deduplication and semantic conflict detection."""
    from pbl4.management_backend.services.event_ingest import (
        ConflictingEventPayloadError,
        ingest_runtime_event,
    )

    attempt_id = f"att-evt-{uuid.uuid4().hex[:8]}"
    job_id = f"job-evt-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO jobs (
                job_id, display_name, description, state, requested_contract,
                resolved_contract, contract_hash, created_at, frozen_at
            ) VALUES (%s, 'Evt Job', '', 'READY', '{}', '{}', 'hash_evt', %s, %s)
            """,
            (job_id, now, now),
        )
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, state, execution_mode, contract_hash, created_at
            ) VALUES (%s, %s, 'RUNNING', 'FRESH', 'hash_evt', %s)
            """,
            (attempt_id, job_id, now),
        )
        pg_conn.commit()

    # 1. Ingest initial event
    result1 = ingest_runtime_event(
        pg_conn,
        attempt_id=attempt_id,
        runtime_event_seq=1,
        event_type="TRAINING_STEP_COMMITTED",
        severity="INFO",
        occurred_at=now,
        payload={"loss": 0.5, "step": 1},
    )
    assert result1.row is not None
    assert result1.inserted is True
    pg_conn.commit()

    # 2. Duplicate event with identical semantic fields -> deduplicated safely
    result2 = ingest_runtime_event(
        pg_conn,
        attempt_id=attempt_id,
        runtime_event_seq=1,
        event_type="TRAINING_STEP_COMMITTED",
        severity="INFO",
        occurred_at=now,
        payload={"loss": 0.5, "step": 1},
    )
    assert result2.row is not None
    assert result2.inserted is False
    assert result2.row["runtime_event_seq"] == 1

    # 3. Conflicting semantic payload -> ConflictingEventPayloadError
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
    """Verify durable HTTP idempotency record acquisition, completion, and conflict detection."""
    from pbl4.management_backend.services import idempotency

    idemp_key = f"idemp-{uuid.uuid4().hex}"
    req_hash = idempotency.compute_request_hash(
        operation="START_ATTEMPT",
        path="/api/v1/jobs/test-job/start",
        body_obj={"note": "first"},
    )

    # 1. First acquisition returns NEW
    _record, action = idempotency.acquire_or_get_record(
        pg_conn,
        endpoint_semantic_scope="JOB_START",
        idempotency_key=idemp_key,
        canonical_request_hash=req_hash,
    )
    assert action == "NEW"
    cmd_id = str(uuid.uuid4())

    # 2. Complete record
    response_payload = {"command_id": cmd_id, "command_state": "ACCEPTED"}
    idempotency.complete_record(
        pg_conn,
        endpoint_semantic_scope="JOB_START",
        idempotency_key=idemp_key,
        response_status_code=202,
        response_body=response_payload,
        command_id=cmd_id,
    )
    pg_conn.commit()

    # 3. Second call with SAME key and SAME request hash returns SUCCEEDED with cached response
    record2, action2 = idempotency.acquire_or_get_record(
        pg_conn,
        endpoint_semantic_scope="JOB_START",
        idempotency_key=idemp_key,
        canonical_request_hash=req_hash,
    )
    assert action2 == "SUCCEEDED"
    assert record2 is not None
    cached_body = record2.get("response_body_jsonb")
    if isinstance(cached_body, str):
        cached_body = json.loads(cached_body)
    assert cached_body["command_id"] == cmd_id

    # 4. Third call with SAME key but DIFFERENT request hash raises IdempotencyConflictError
    diff_hash = idempotency.compute_request_hash(
        operation="START_ATTEMPT",
        path="/api/v1/jobs/test-job/start",
        body_obj={"note": "DIFFERENT_BODY"},
    )
    with pytest.raises(idempotency.IdempotencyConflictError) as exc_info:
        idempotency.acquire_or_get_record(
            pg_conn,
            endpoint_semantic_scope="JOB_START",
            idempotency_key=idemp_key,
            canonical_request_hash=diff_hash,
        )
    assert exc_info.value.code == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"
    pg_conn.rollback()

    concurrent_key = f"idemp-race-{uuid.uuid4().hex}"
    barrier = threading.Barrier(2)

    def acquire_once() -> str:
        with psycopg.connect(TEST_DB_URL) as conn:
            barrier.wait()
            try:
                _record, result = idempotency.acquire_or_get_record(
                    conn,
                    endpoint_semantic_scope="JOB_START_RACE",
                    idempotency_key=concurrent_key,
                    canonical_request_hash=req_hash,
                )
                conn.commit()
                return result
            except idempotency.RequestInProgressError:
                conn.rollback()
                return "IN_PROGRESS"

    with ThreadPoolExecutor(max_workers=2) as executor:
        race_results = list(executor.map(lambda _index: acquire_once(), range(2)))

    assert race_results.count("NEW") == 1
    assert race_results.count("IN_PROGRESS") == 1


def test_06_command_durability(pg_conn):
    """Verify durable command persistence, failure recording, and update."""
    from pbl4.management_backend.repositories import command_repository
    from pbl4.management_backend.services import idempotency

    command_id = str(uuid.uuid4())
    idemp_key = f"idemp-dur-{uuid.uuid4().hex}"
    now = datetime.now(UTC)

    # 1. Command persisted as PENDING
    cmd = command_repository.create_command(
        pg_conn,
        command_id=command_id,
        command_type="START_ATTEMPT",
        target_type="ATTEMPT",
        target_id="att-123",
        request={"execution_mode": "FRESH"},
        requested_at=now,
    )
    assert cmd["state"] == "PENDING"
    pg_conn.commit()

    # 2. Simulated downstream timeout/failure: command remains PENDING (never mutated to FAILED)
    idempotency.record_dispatch_failure(
        pg_conn,
        endpoint_semantic_scope="JOB_START",
        idempotency_key=idemp_key,
        command_id=command_id,
        resource_id="att-123",
    )
    pg_conn.commit()

    fetched = command_repository.get_command(pg_conn, command_id)
    assert fetched is not None
    assert fetched["state"] == "PENDING"

    # 3. Upon receiving downstream acceptance, command is updated to ACCEPTED
    updated = command_repository.update_command_state(
        pg_conn,
        command_id=command_id,
        new_state="ACCEPTED",
        dispatched_at=datetime.now(UTC),
        result={"status": "OK"},
    )
    assert updated["state"] == "ACCEPTED"
    pg_conn.commit()


def test_07_dataset_registration_transaction(pg_conn):
    """Verify dataset manifest verification, short DB transaction, and registration ACK."""
    from pbl4.management_backend import db
    from pbl4.management_backend.services import dataset_service
    from pbl4.management_backend.services.dataset_service import DatasetManifestVerificationError

    build_id = f"bld-reg-{uuid.uuid4().hex[:8]}"
    dataset_id = f"ds-reg-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    # Create parent dataset and initial build row
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO datasets (
                dataset_id, name, task_type, source_type, source_reference, created_at
            )
            VALUES (%s, %s, 'image_classification', 'builtin', 'cifar10', %s)
            """,
            (dataset_id, "Reg Test Dataset", now),
        )
        cur.execute(
            """
            INSERT INTO dataset_builds (
                dataset_build_id, dataset_id, profile, batch_size, shard_count, partition_seed,
                input_shape_json, dtype, num_classes, preprocessing_json, state, created_at
            ) VALUES (
                %s, %s, 'CNN_IMAGE_CLASSIFICATION_V1', 64, 3, 42,
                '[3, 32, 32]', 'float32', 10, '{}', 'VERIFYING', %s
            )
            """,
            (build_id, dataset_id, now),
        )
        pg_conn.commit()

    manifest_data = {"version": 1, "shard_count": 3, "sample_count": 1000}
    manifest_bytes = json.dumps(manifest_data, separators=(",", ":")).encode()
    computed_hash = hashlib.sha256(manifest_bytes).hexdigest()

    mock_client = MagicMock()
    # 1. Mismatched manifest hash raises DatasetManifestVerificationError
    mock_client.get_build.return_value = {
        "dataset_build_id": build_id,
        "state": "REGISTERING",
        "dataset_manifest_hash": "wrong_hash",
        "manifest_uri": f"http://dm:8001/builds/{build_id}/manifest",
        "artifact_base_url": f"http://dm:8001/builds/{build_id}/artifacts",
        "shard_count": 3,
        "sample_count": 1000,
    }
    mock_client.get_manifest.return_value = (manifest_data, manifest_bytes)

    with (
        patch(
            "pbl4.management_backend.services.dataset_service.get_client", return_value=mock_client
        ),
        pytest.raises(DatasetManifestVerificationError),
    ):
        dataset_service.verify_and_register_build(db, build_id)

    # Matching status hash persists the catalog and sends a stable registration ACK.
    mock_client.get_build.return_value["dataset_manifest_hash"] = computed_hash
    mock_client.registration_ack.side_effect = [
        RuntimeError("ACK timeout"),
        {"dataset_build_id": build_id, "state": "READY"},
    ]

    with (
        patch(
            "pbl4.management_backend.services.dataset_service.get_client",
            return_value=mock_client,
        ),
        pytest.raises(RuntimeError, match="ACK timeout"),
    ):
        dataset_service.verify_and_register_build(db, build_id)
    first_registration_id = mock_client.registration_ack.call_args.kwargs["registration_id"]

    with patch(
        "pbl4.management_backend.services.dataset_service.get_client", return_value=mock_client
    ):
        res = dataset_service.verify_and_register_build(
            db,
            build_id,
            manifest_uri="https://caller.invalid/manifest.json",
            artifact_base_url="https://caller.invalid/artifacts",
        )
        assert res["state"] == "READY"
        assert res["manifest_uri"] == mock_client.get_build.return_value["manifest_uri"]
        assert res["artifact_base_url"] == mock_client.get_build.return_value["artifact_base_url"]
        assert mock_client.registration_ack.call_count == 2
        assert mock_client.registration_ack.call_args.kwargs["registration_id"] == (
            first_registration_id
        )
