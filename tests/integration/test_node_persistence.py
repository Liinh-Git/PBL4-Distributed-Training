"""Integration tests for Phase 4: Node Agent persistence, migration 0003, and repositories.

Tests run against real PostgreSQL database.
Covers:
- Migration 0003 upgrade, schema structure, downgrade, re-upgrade.
- Node enrollment code storage, atomic one-time consumption, expiry.
- Nodes table CRUD, default state OFFLINE, heartbeat, resources, revocation.
- Worker allocations CRUD, actual/desired state, terminal release.
- Partial unique active allocation constraint (at most one active per node).
- Foreign keys to attempts and nodes.
- Extended worker_sessions with nullable node_id and allocation_id.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import errors

from pbl4.management_backend.repositories import (
    allocation_repository,
    node_enrollment_repository,
    node_repository,
    worker_session_repository,
)

TEST_DB_URL = (
    os.environ.get("TEST_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://postgres:123456@localhost:5432/pbl4_test"
)


def _is_db_available() -> bool:
    try:
        with psycopg.connect(TEST_DB_URL, connect_timeout=3):
            return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_db_available(),
    reason=f"PostgreSQL database not accessible at {TEST_DB_URL}",
)


@pytest.fixture(scope="module")
def pg_conn():
    """Module-level PostgreSQL connection with automatic rollback/cleanup."""
    conn = psycopg.connect(TEST_DB_URL, autocommit=False)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def clean_tx(pg_conn):
    """Function-level fixture ensuring a clean transaction per test."""
    try:
        pg_conn.rollback()
    except Exception:
        pass
    yield pg_conn
    try:
        pg_conn.rollback()
    except Exception:
        pass


def _create_test_job_and_attempt(conn: psycopg.Connection) -> tuple[str, str]:
    """Helper to insert valid parent job and attempt for foreign key satisfaction."""
    job_id = f"job-{uuid.uuid4().hex[:8]}"
    attempt_id = f"att-{uuid.uuid4().hex[:8]}"
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
                "Integration Job",
                "Job for integration tests",
                "READY",
                json.dumps({"dataset_build_id": "bld-test"}),
                json.dumps({"synchronization": {"expected_workers": 2}}),
                "hash-1234",
                now,
                now,
            ),
        )
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, state, execution_mode, contract_hash, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (attempt_id, job_id, "RUNNING", "FRESH", "hash-1234", now),
        )
    return job_id, attempt_id


# =========================================================================
# 1. Migration tests (upgrade, downgrade, re-upgrade, schema check)
# =========================================================================


def test_01_migration_upgrade_downgrade_cycle():
    """Verify migration 0003 upgrade, downgrade, and re-upgrade work cleanly."""
    repo_root = Path(__file__).resolve().parents[2]
    alembic_ini = repo_root / "alembic.ini"
    assert alembic_ini.is_file(), f"alembic.ini missing at {alembic_ini}"

    alembic_cfg = Config(str(alembic_ini))
    alembic_cfg.set_main_option("sqlalchemy.url", TEST_DB_URL.replace("%", "%%"))

    # Upgrade to head
    command.upgrade(alembic_cfg, "head")

    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            # Check tables exist
            cur.execute("SELECT to_regclass('node_enrollment_codes')")
            assert cur.fetchone()[0] == "node_enrollment_codes"
            cur.execute("SELECT to_regclass('nodes')")
            assert cur.fetchone()[0] == "nodes"
            cur.execute("SELECT to_regclass('worker_allocations')")
            assert cur.fetchone()[0] == "worker_allocations"

            # Check columns in worker_sessions
            cur.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'worker_sessions' AND column_name IN ('node_id', 'allocation_id')
                """
            )
            cols = {row[0] for row in cur.fetchall()}
            assert cols == {"node_id", "allocation_id"}

    # Downgrade 1 revision (0003 -> 0002)
    command.downgrade(alembic_cfg, "-1")

    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('node_enrollment_codes')")
            assert cur.fetchone()[0] is None
            cur.execute("SELECT to_regclass('nodes')")
            assert cur.fetchone()[0] is None
            cur.execute("SELECT to_regclass('worker_allocations')")
            assert cur.fetchone()[0] is None

    # Re-upgrade to head
    command.upgrade(alembic_cfg, "head")

    with psycopg.connect(TEST_DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('nodes')")
            assert cur.fetchone()[0] == "nodes"


# =========================================================================
# 2. Node enrollment code tests (creation, atomic consumption, expiry)
# =========================================================================


def test_02_enrollment_code_insert_and_atomic_consumption(clean_tx):
    """Verify insertion and atomic single-use consumption of enrollment codes."""
    raw_code = secrets.token_hex(16)
    code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=10)

    # 5. Insert code hash
    rec = node_enrollment_repository.create_enrollment_code(
        clean_tx,
        code_hash=code_hash,
        created_at=now,
        expires_at=expires_at,
    )
    assert rec["code_hash"] == code_hash
    assert rec["used_at"] is None

    # 6. Consume code successfully
    consumed = node_enrollment_repository.consume_code_if_valid(
        clean_tx,
        code_hash=code_hash,
        now=now + timedelta(seconds=1),
    )
    assert consumed is not None
    assert consumed["used_at"] is not None

    # 7. Consume a second time must fail (already used)
    consumed_again = node_enrollment_repository.consume_code_if_valid(
        clean_tx,
        code_hash=code_hash,
        now=now + timedelta(seconds=2),
    )
    assert consumed_again is None


def test_03_expired_enrollment_code_rejected(clean_tx):
    """Verify expired enrollment code cannot be consumed."""
    code_hash = hashlib.sha256(b"expired-code").hexdigest()
    now = datetime.now(UTC)
    created_at = now - timedelta(hours=1)
    expires_at = now - timedelta(minutes=5)  # expired 5 mins ago

    node_enrollment_repository.create_enrollment_code(
        clean_tx,
        code_hash=code_hash,
        created_at=created_at,
        expires_at=expires_at,
    )

    consumed = node_enrollment_repository.consume_code_if_valid(
        clean_tx,
        code_hash=code_hash,
        now=now,
    )
    assert consumed is None


def test_04_atomic_concurrency_race_condition_proof(pg_conn):
    """Prove atomic one-time consumption: 10 parallel threads attempt to consume the same code."""
    code_hash = hashlib.sha256(f"race-{uuid.uuid4().hex}".encode("utf-8")).hexdigest()
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=15)

    with psycopg.connect(TEST_DB_URL, autocommit=True) as init_conn:
        node_enrollment_repository.create_enrollment_code(
            init_conn,
            code_hash=code_hash,
            created_at=now,
            expires_at=expires_at,
        )

    def attempt_consume(idx: int) -> bool:
        with psycopg.connect(TEST_DB_URL, autocommit=True) as thread_conn:
            res = node_enrollment_repository.consume_code_if_valid(
                thread_conn,
                code_hash=code_hash,
                now=datetime.now(UTC),
            )
            return res is not None

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(attempt_consume, range(10)))

    # Exactly ONE thread must succeed; 9 must fail
    assert results.count(True) == 1
    assert results.count(False) == 9


# =========================================================================
# 3. Nodes repository tests (CRUD, default OFFLINE, heartbeat, resources, revocation)
# =========================================================================


def test_05_node_lifecycle_and_state_management(clean_tx):
    """Verify node creation, default OFFLINE state, heartbeat, telemetry update, and revocation."""
    node_id = f"node-{uuid.uuid4().hex[:8]}"
    cred_hash = hashlib.sha256(b"secret").hexdigest()
    now = datetime.now(UTC)

    # 10 & 11. Create node; default state is OFFLINE
    node = node_repository.create_node(
        clean_tx,
        node_id=node_id,
        display_name="Worker Host 01",
        credential_hash=cred_hash,
        credential_created_at=now,
        capabilities_jsonb={"gpu_count": 1, "cpu_count": 16},
        enrolled_at=now,
    )
    assert node["node_id"] == node_id
    assert node["state"] == "OFFLINE"
    assert node["last_seen_at"] is None

    # 12. Update heartbeat
    seen_time = now + timedelta(seconds=10)
    updated = node_repository.update_heartbeat(clean_tx, node_id, seen_time)
    assert updated["last_seen_at"] == seen_time

    # 13. Update resources
    res_snap = {"cpu_util": 25.5, "ram_used": 1024**3}
    with_res = node_repository.update_resources(clean_tx, node_id, res_snap)
    assert with_res["latest_resources_jsonb"]["cpu_util"] == 25.5

    # 14. Update state to ONLINE
    online_node = node_repository.update_state(clean_tx, node_id, "ONLINE")
    assert online_node["state"] == "ONLINE"

    # 15. Revoke node
    revoked_time = now + timedelta(minutes=5)
    revoked = node_repository.revoke_node(clean_tx, node_id, revoked_time)
    assert revoked["state"] == "REVOKED"
    assert revoked["credential_revoked_at"] == revoked_time

    # Listing nodes
    listed = node_repository.list_nodes(clean_tx, state="REVOKED")
    assert any(n["node_id"] == node_id for n in listed)


# =========================================================================
# 4. Worker Allocation tests & Partial Unique Constraint
# =========================================================================


def test_06_worker_allocation_crud_and_lifecycle(clean_tx):
    """Verify worker allocation creation, state transitions, and listing."""
    job_id, attempt_id = _create_test_job_and_attempt(clean_tx)
    node_id = f"node-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    node_repository.create_node(
        clean_tx,
        node_id=node_id,
        display_name="Node Alloc Test",
        credential_hash=hashlib.sha256(b"s").hexdigest(),
        credential_created_at=now,
        capabilities_jsonb={},
        enrolled_at=now,
    )

    alloc_id = f"alloc-{uuid.uuid4().hex[:8]}"

    # 16. Create allocation
    alloc = allocation_repository.create_allocation(
        clean_tx,
        allocation_id=alloc_id,
        attempt_id=attempt_id,
        node_id=node_id,
        device="cuda:0",
        runtime_endpoint="127.0.0.1:9000",
        created_at=now,
        resource_allocation_jsonb={"gpu_index": 0},
    )
    assert alloc["allocation_id"] == alloc_id
    assert alloc["desired_state"] == "RUNNING"
    assert alloc["actual_state"] == "REQUESTED"

    # 17. List for attempt
    attempt_allocs = allocation_repository.list_for_attempt(clean_tx, attempt_id)
    assert len(attempt_allocs) == 1
    assert attempt_allocs[0]["allocation_id"] == alloc_id

    # 18. List active
    active = allocation_repository.list_active(clean_tx, node_id=node_id)
    assert len(active) == 1
    assert active[0]["allocation_id"] == alloc_id

    # 19. Update actual state to STARTED
    started_time = now + timedelta(seconds=5)
    updated_act = allocation_repository.update_actual_state(
        clean_tx,
        alloc_id,
        "STARTED",
        started_at=started_time,
    )
    assert updated_act["actual_state"] == "STARTED"
    assert updated_act["started_at"] == started_time

    # 20. Update desired state to STOPPED
    updated_des = allocation_repository.update_desired_state(clean_tx, alloc_id, "STOPPED")
    assert updated_des["desired_state"] == "STOPPED"

    # 21. Terminal update to ENDED
    ended_time = now + timedelta(minutes=1)
    terminal = allocation_repository.terminal_update(
        clean_tx,
        alloc_id,
        "ENDED",
        ended_at=ended_time,
    )
    assert terminal["actual_state"] == "ENDED"
    assert terminal["ended_at"] == ended_time

    # Active allocations must now be empty
    active_now = allocation_repository.list_active(clean_tx, node_id=node_id)
    assert len(active_now) == 0


def test_07_one_active_allocation_per_node_constraint(clean_tx):
    """Verify partial unique index uq_worker_allocations__one_active_per_node enforces 1 active allocation."""
    job_id, attempt_id = _create_test_job_and_attempt(clean_tx)
    node_id = f"node-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    node_repository.create_node(
        clean_tx,
        node_id=node_id,
        display_name="Node Constraint Test",
        credential_hash=hashlib.sha256(b"s").hexdigest(),
        credential_created_at=now,
        capabilities_jsonb={},
        enrolled_at=now,
    )

    # First active allocation on node
    alloc1_id = f"alloc-1-{uuid.uuid4().hex[:8]}"
    allocation_repository.create_allocation(
        clean_tx,
        allocation_id=alloc1_id,
        attempt_id=attempt_id,
        node_id=node_id,
        device="cpu",
        runtime_endpoint="127.0.0.1:9000",
        created_at=now,
        actual_state="REQUESTED",
    )

    # 22. Second active allocation on SAME node must violate partial unique index
    alloc2_id = f"alloc-2-{uuid.uuid4().hex[:8]}"
    with pytest.raises(errors.UniqueViolation):
        allocation_repository.create_allocation(
            clean_tx,
            allocation_id=alloc2_id,
            attempt_id=attempt_id,
            node_id=node_id,
            device="cpu",
            runtime_endpoint="127.0.0.1:9000",
            created_at=now,
            actual_state="DISPATCHED",
        )

    # Roll back the failed statement within clean_tx
    clean_tx.rollback()

    # Re-insert attempt and node for second part of test
    _job_id2, attempt2_id = _create_test_job_and_attempt(clean_tx)
    node2_id = f"node-{uuid.uuid4().hex[:8]}"
    node_repository.create_node(
        clean_tx,
        node_id=node2_id,
        display_name="Node History Test",
        credential_hash=hashlib.sha256(b"s").hexdigest(),
        credential_created_at=now,
        capabilities_jsonb={},
        enrolled_at=now,
    )

    # 23. Multiple terminal (historical) allocations CAN exist on the same node
    for i in range(3):
        h_id = f"alloc-hist-{i}-{uuid.uuid4().hex[:8]}"
        allocation_repository.create_allocation(
            clean_tx,
            allocation_id=h_id,
            attempt_id=attempt2_id,
            node_id=node2_id,
            device="cpu",
            runtime_endpoint="127.0.0.1:9000",
            created_at=now,
            actual_state="ENDED",  # terminal state!
        )


def test_08_foreign_key_constraints_enforced(clean_tx):
    """Verify Foreign Keys on attempt_id and node_id."""
    now = datetime.now(UTC)
    # Attempt does not exist
    with pytest.raises(errors.ForeignKeyViolation):
        allocation_repository.create_allocation(
            clean_tx,
            allocation_id=f"alloc-{uuid.uuid4().hex[:8]}",
            attempt_id="nonexistent-attempt",
            node_id="nonexistent-node",
            device="cpu",
            runtime_endpoint="127.0.0.1:9000",
            created_at=now,
        )


# =========================================================================
# 5. Extended worker_sessions repository tests
# =========================================================================


def test_09_worker_sessions_with_nullable_node_and_allocation(clean_tx):
    """Verify worker_sessions supports node_id, allocation_id and works with nulls."""
    _job_id, attempt_id = _create_test_job_and_attempt(clean_tx)
    node_id = f"node-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)

    node_repository.create_node(
        clean_tx,
        node_id=node_id,
        display_name="Node Session Test",
        credential_hash=hashlib.sha256(b"s").hexdigest(),
        credential_created_at=now,
        capabilities_jsonb={},
        enrolled_at=now,
    )

    alloc_id = f"alloc-{uuid.uuid4().hex[:8]}"
    allocation_repository.create_allocation(
        clean_tx,
        allocation_id=alloc_id,
        attempt_id=attempt_id,
        node_id=node_id,
        device="cpu",
        runtime_endpoint="127.0.0.1:9000",
        created_at=now,
    )

    # 25 & 26. Managed session with node_id and allocation_id
    sess_managed = worker_session_repository.upsert_session(
        clean_tx,
        session_id=1001,
        attempt_id=attempt_id,
        worker_id=0,
        node_label="worker-managed",
        protocol_version=1,
        state="CONNECTING",
        connected_at=now,
        node_id=node_id,
        allocation_id=alloc_id,
    )
    assert sess_managed["node_id"] == node_id
    assert sess_managed["allocation_id"] == alloc_id

    # 27. Legacy / unmanaged session with null node_id and allocation_id
    sess_unmanaged = worker_session_repository.upsert_session(
        clean_tx,
        session_id=1002,
        attempt_id=attempt_id,
        worker_id=1,
        node_label="worker-dev-manual",
        protocol_version=1,
        state="CONNECTING",
        connected_at=now,
        node_id=None,
        allocation_id=None,
    )
    assert sess_unmanaged["node_id"] is None
    assert sess_unmanaged["allocation_id"] is None

    # Update snapshot projection
    updated_proj = worker_session_repository.update_snapshot_projection(
        clean_tx,
        session_id=1001,
        attempt_id=attempt_id,
        worker_id=0,
        node_label="worker-managed-renamed",
        state="READY",
        last_heartbeat_at=now + timedelta(seconds=10),
    )
    assert updated_proj["node_label"] == "worker-managed-renamed"
    assert updated_proj["state"] == "READY"
    assert updated_proj["node_id"] == node_id  # preserved
    assert updated_proj["allocation_id"] == alloc_id  # preserved
