"""Integration tests for Attempt Orchestration, Node Dispatch, and Snapshot Recovery.

Reference:
- docs/NODE_AGENT_IMPLEMENTATION_PLAN.md Sections 4.7, 4.10, 6.3, 8.2
- Phase 8 Scope & Acceptance Criteria

Tests:
1. Success:
   - expected_workers = N -> select N nodes -> create N allocations -> commit ->
     START_ATTEMPT accepted -> START_WORKER dispatched to N nodes with exact seeds & tokens.
2. Insufficient nodes:
   - ONLINE nodes < expected_workers -> fails cleanly, no orphaned attempts or allocations.
3. Runtime rejection:
   - START_ATTEMPT -> REJECTED -> no START_WORKER dispatched.
4. Partial worker-start failure:
   - One node fails START_WORKER -> failed allocation recorded, already-started workers
     receive STOP_WORKER, ABORT_ATTEMPT dispatched to Runtime.
5. Retry:
   - Retry creates fresh attempt, fresh allocations, and fresh tokens (no reuse of terminal state).
6. Snapshot projection & recovery:
   - worker_id -> allocation_id -> node_id mapping projected via StateSnapshot,
     persisted in worker_sessions, and recoverable across restarts.
"""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime
import json
import os
from typing import Any
from unittest.mock import MagicMock, patch
import uuid

import psycopg
import pytest

from pbl4.agent_protocol.messages import StartWorkerPayload, StopWorkerPayload
from pbl4.common.worker_admission import verify_worker_join_token
from pbl4.management_backend import db
from pbl4.management_backend.config import BackendSettings, get_settings
from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway
from pbl4.management_backend.repositories import (
    allocation_repository,
    attempt_repository,
    job_repository,
    worker_session_repository,
)
from pbl4.management_backend.services import attempt_service
from pbl4.management_backend.services.allocation_service import AllocationService
from pbl4.management_protocol.messages import StateSnapshot

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


@pytest.fixture(scope="module", autouse=True)
def init_test_db_pool():
    """Initialize DB connection pool for attempt orchestration tests."""
    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ["PBL4_WORKER_ADMISSION_SECRET"] = "integration-test-secret-key-32-chars!"
    db.init_pool(TEST_DB_URL, min_size=1, max_size=5)
    yield
    db.close_pool()


@pytest.fixture
def pg_conn():
    """PostgreSQL connection for direct verifications."""
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clean_db(pg_conn):
    """Clean active attempts and set existing nodes OFFLINE before and after each test."""
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
        cur.execute("UPDATE nodes SET state = 'OFFLINE' WHERE state = 'ONLINE'")
    yield
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
        cur.execute("UPDATE nodes SET state = 'OFFLINE' WHERE state = 'ONLINE'")


def _create_test_job(
    conn: psycopg.Connection,
    *,
    expected_workers: int = 2,
    training_seed: int = 4242,
) -> str:
    job_id = f"job-orch-{uuid.uuid4().hex[:8]}"
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
                f"Test Job {job_id}",
                "Attempt orchestration test job",
                "READY",
                json.dumps({"dataset_build_id": "bld-1"}),
                json.dumps({
                    "synchronization": {"expected_workers": expected_workers},
                    "training": {"training_seed": training_seed},
                }),
                f"hash-{job_id}",
                now,
                now,
            ),
        )
    return job_id


def _enroll_test_nodes(
    conn: psycopg.Connection,
    node_ids: list[str],
    *,
    state: str = "ONLINE",
    has_gpu: bool = False,
) -> None:
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        for nid in node_ids:
            caps: dict[str, Any] = {
                "gpu_count": 1 if has_gpu else 0,
                "gpus": [{"index": 0, "name": "Test GPU"}] if has_gpu else [],
            }
            cur.execute(
                """
                INSERT INTO nodes (
                    node_id, display_name, credential_hash, credential_created_at,
                    capabilities_jsonb, enrolled_at, state
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (node_id) DO UPDATE
                SET state = EXCLUDED.state,
                    capabilities_jsonb = EXCLUDED.capabilities_jsonb
                """,
                (
                    nid,
                    f"Node {nid}",
                    "test_hash",
                    now,
                    json.dumps(caps),
                    now,
                    state,
                ),
            )


def test_start_attempt_success_orchestration(pg_conn):
    """Verify complete successful attempt orchestration:
    expected_workers = 2 -> 2 ONLINE nodes selected -> allocations created (REQUESTED) ->
    DB committed -> START_ATTEMPT accepted -> START_WORKER dispatched with tokens & seed.
    """
    job_id = _create_test_job(pg_conn, expected_workers=2, training_seed=777)
    node_0 = f"node-succ-0-{uuid.uuid4().hex[:6]}"
    node_1 = f"node-succ-1-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_1, node_0])  # Unsorted order to test deterministic sorting

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-test",
        "command_type": "START_ATTEMPT",
    }

    dispatched_starts: list[tuple[str, StartWorkerPayload]] = []
    mock_node_gw = MagicMock()

    def fake_send_start_worker(node_id: str, *, command: StartWorkerPayload) -> bool:
        dispatched_starts.append((node_id, command))
        return True

    mock_node_gw.send_start_worker.side_effect = fake_send_start_worker

    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw), \
         patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw):
        attempt_row, cmd_row = attempt_service.execute_start_job(
            db,
            job_id,
            idempotency_key=f"ik-{uuid.uuid4().hex}",
        )

    attempt_id = attempt_row["attempt_id"]
    assert attempt_row["state"] == "CREATED"
    assert cmd_row["command_type"] == "START_ATTEMPT"

    # Runtime command was dispatched
    mock_rt_gw.send_command_and_wait_result.assert_called_once()

    # Allocations created and committed in DB
    allocs = allocation_repository.list_for_attempt(pg_conn, attempt_id)
    assert len(allocs) == 2

    # Deterministic node assignment
    sorted_nodes = sorted([node_0, node_1])
    assert [a["node_id"] for a in allocs] == sorted_nodes

    # All allocations updated to DISPATCHED
    for a in allocs:
        assert a["actual_state"] == allocation_repository.ACTUAL_STATE_DISPATCHED
        assert a["desired_state"] == allocation_repository.DESIRED_STATE_RUNNING

    # Verify START_WORKER calls
    assert len(dispatched_starts) == 2
    secret = get_settings().worker_admission_secret

    for nid, payload in dispatched_starts:
        assert payload.attempt_id == attempt_id
        assert payload.initialization_seed == 777
        assert payload.runtime_host == get_settings().dtp_advertised_host
        assert payload.runtime_port == get_settings().runtime_dtp_port

        # Verify admission token claims
        claims = verify_worker_join_token(
            secret=secret,
            token=payload.worker_join_token,
            expected_attempt_id=attempt_id,
            expected_allocation_id=payload.allocation_id,
            expected_node_id=nid,
        )
        assert claims.attempt_id == attempt_id
        assert claims.allocation_id == payload.allocation_id
        assert claims.node_id == nid


def test_start_attempt_insufficient_nodes_rollback(pg_conn):
    """Verify that if available ONLINE nodes < expected_workers, the attempt
    fails cleanly, rolling back any partial attempt or allocation creation.
    """
    job_id = _create_test_job(pg_conn, expected_workers=3)
    # Only enroll 2 ONLINE nodes
    node_0 = f"node-insuff-0-{uuid.uuid4().hex[:6]}"
    node_1 = f"node-insuff-1-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_0, node_1])

    mock_rt_gw = MagicMock()
    mock_node_gw = MagicMock()

    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw), \
         patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw):
        with pytest.raises(attempt_service.NodeCapacityUnavailableError) as exc_info:
            attempt_service.execute_start_job(
                db,
                job_id,
                idempotency_key=f"ik-{uuid.uuid4().hex}",
            )
        assert exc_info.value.code == "NODE_CAPACITY_UNAVAILABLE"

    # Verify no active attempt left in DB for this job
    attempts = attempt_repository.list_attempts(pg_conn, job_id=job_id)
    assert len(attempts) == 0

    # Verify no allocations created
    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM worker_allocations WHERE node_id IN (%s, %s)", (node_0, node_1))
        count = cur.fetchone()[0]
        assert count == 0

    # Verify neither Runtime nor Node gateway were called
    mock_rt_gw.send_command_and_wait_result.assert_not_called()
    mock_node_gw.send_start_worker.assert_not_called()


def test_start_attempt_runtime_rejection_no_worker_dispatch(pg_conn):
    """Verify that when Runtime REJECTS START_ATTEMPT, NO START_WORKER commands
    are dispatched to nodes, and command error is raised.
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    node_0 = f"node-rej-0-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_0])

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "REJECTED",
        "command_id": "cmd-test-rej",
        "command_type": "START_ATTEMPT",
        "result": {
            "code": "COMMAND_REJECTED",
            "message": "Parameter server out of memory",
        },
    }

    mock_node_gw = MagicMock()

    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw), \
         patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw):
        with pytest.raises(attempt_service.CommandRejectedError) as exc_info:
            attempt_service.execute_start_job(
                db,
                job_id,
                idempotency_key=f"ik-{uuid.uuid4().hex}",
            )
        assert exc_info.value.code == "COMMAND_REJECTED"

    # Runtime was called
    mock_rt_gw.send_command_and_wait_result.assert_called_once()

    # NodeControlGateway send_start_worker was NEVER called
    mock_node_gw.send_start_worker.assert_not_called()

    # DB allocations remain in REQUESTED state (never dispatched)
    attempts = attempt_repository.list_attempts(pg_conn, job_id=job_id)
    assert len(attempts) == 1
    attempt_id = attempts[0]["attempt_id"]
    allocs = allocation_repository.list_for_attempt(pg_conn, attempt_id)
    assert len(allocs) == 1
    assert allocs[0]["actual_state"] == allocation_repository.ACTUAL_STATE_REQUESTED


def test_start_attempt_partial_worker_dispatch_failure(pg_conn):
    """Verify partial failure handling during START_WORKER:
    Node A succeeds, Node B fails ->
    - Node B allocation marked FAILED
    - Node A allocation desired_state updated to STOPPED
    - Node A sent best-effort STOP_WORKER
    - Runtime sent ABORT_ATTEMPT
    - CommandFailedError(code='WORKER_SPAWN_FAILED') raised.
    """
    job_id = _create_test_job(pg_conn, expected_workers=2)
    node_0 = f"node-part-0-{uuid.uuid4().hex[:6]}"
    node_1 = f"node-part-1-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_0, node_1])

    sorted_nodes = sorted([node_0, node_1])
    succ_node = sorted_nodes[0]
    fail_node = sorted_nodes[1]

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-test-part",
        "command_type": "START_ATTEMPT",
    }

    mock_node_gw = MagicMock()
    stops_sent: list[str] = []

    def fake_send_start_worker(node_id: str, *, command: StartWorkerPayload) -> bool:
        if node_id == succ_node:
            return True
        return False  # fail_node fails dispatch

    def fake_send_stop_worker(node_id: str, *, command: StopWorkerPayload) -> bool:
        stops_sent.append(node_id)
        return True

    mock_node_gw.send_start_worker.side_effect = fake_send_start_worker
    mock_node_gw.send_stop_worker.side_effect = fake_send_stop_worker

    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw), \
         patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw):
        with pytest.raises(attempt_service.CommandFailedError) as exc_info:
            attempt_service.execute_start_job(
                db,
                job_id,
                idempotency_key=f"ik-{uuid.uuid4().hex}",
            )
        assert exc_info.value.code == "WORKER_SPAWN_FAILED"

    # Runtime was sent ABORT_ATTEMPT
    calls = mock_rt_gw.send_command_and_wait_result.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs.get("command_type") == "START_ATTEMPT"
    assert calls[1].kwargs.get("command_type") == "ABORT_ATTEMPT"

    # succ_node was sent STOP_WORKER
    assert succ_node in stops_sent

    # Verify allocations state in DB
    attempts = attempt_repository.list_attempts(pg_conn, job_id=job_id)
    attempt_id = attempts[0]["attempt_id"]
    allocs = allocation_repository.list_for_attempt(pg_conn, attempt_id)
    alloc_map = {a["node_id"]: a for a in allocs}

    # succ_node had desired_state set to STOPPED
    assert alloc_map[succ_node]["desired_state"] == allocation_repository.DESIRED_STATE_STOPPED
    # fail_node was marked FAILED
    assert alloc_map[fail_node]["actual_state"] == allocation_repository.ACTUAL_STATE_FAILED
    assert alloc_map[fail_node]["failure_code"] == "NODE_DISPATCH_FAILED"


def test_retry_creates_fresh_allocations_and_tokens(pg_conn):
    """Verify retry creates a brand new attempt with fresh allocation_ids and tokens,
    without reusing or resurrecting terminal allocations.
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    node_0 = f"node-ret-0-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_0])

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-test-1",
        "command_type": "START_ATTEMPT",
    }

    mock_node_gw = MagicMock()
    mock_node_gw.send_start_worker.return_value = True

    # 1. First attempt starts and completes/fails
    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw), \
         patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw):
        attempt_1, _ = attempt_service.execute_start_job(
            db,
            job_id,
            idempotency_key=f"ik-{uuid.uuid4().hex}",
        )

    att1_id = attempt_1["attempt_id"]
    allocs_1 = allocation_repository.list_for_attempt(pg_conn, att1_id)
    alloc1_id = allocs_1[0]["allocation_id"]

    # Terminate attempt 1 and its allocation
    attempt_repository.update_attempt_state(pg_conn, att1_id, "FAILED")
    allocation_repository.update_actual_state(
        pg_conn,
        alloc1_id,
        allocation_repository.ACTUAL_STATE_FAILED,
        ended_at=datetime.now(UTC),
    )

    # 2. Retry the job
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-test-2",
        "command_type": "START_ATTEMPT",
    }

    dispatched_payloads: list[StartWorkerPayload] = []

    def fake_send_start(node_id: str, *, command: StartWorkerPayload) -> bool:
        dispatched_payloads.append(command)
        return True

    mock_node_gw.send_start_worker.side_effect = fake_send_start

    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw), \
         patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw):
        attempt_2, _ = attempt_service.execute_retry_job(
            db,
            job_id,
            idempotency_key=f"ik-{uuid.uuid4().hex}",
        )

    att2_id = attempt_2["attempt_id"]
    assert att2_id != att1_id

    allocs_2 = allocation_repository.list_for_attempt(pg_conn, att2_id)
    assert len(allocs_2) == 1
    alloc2_id = allocs_2[0]["allocation_id"]

    # Fresh allocation_id, not reusing old terminal allocation
    assert alloc2_id != alloc1_id
    assert allocs_2[0]["actual_state"] == allocation_repository.ACTUAL_STATE_DISPATCHED

    # Fresh token scoped to new allocation and new attempt
    assert len(dispatched_payloads) == 1
    new_cmd = dispatched_payloads[0]
    assert new_cmd.attempt_id == att2_id
    assert new_cmd.allocation_id == alloc2_id

    secret = get_settings().worker_admission_secret
    claims = verify_worker_join_token(
        secret=secret,
        token=new_cmd.worker_join_token,
        expected_attempt_id=att2_id,
        expected_allocation_id=alloc2_id,
        expected_node_id=node_0,
    )
    assert claims.attempt_id == att2_id
    assert claims.allocation_id == alloc2_id


def test_snapshot_reconciliation_and_backend_recovery(pg_conn):
    """Verify that worker_id -> allocation_id -> node_id mapping from Runtime
    StateSnapshot is persisted in worker_sessions and survives backend recovery.
    """
    job_id = _create_test_job(pg_conn, expected_workers=2)
    node_0 = f"node-snap-0-{uuid.uuid4().hex[:6]}"
    node_1 = f"node-snap-1-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_0, node_1])

    attempt_id = f"att-snap-{uuid.uuid4().hex[:8]}"
    attempt_repository.create_attempt(
        pg_conn,
        attempt_id=attempt_id,
        job_id=job_id,
        contract_hash=f"hash-{job_id}",
        execution_mode="FRESH",
        created_at=datetime.now(UTC),
    )
    attempt_repository.update_attempt_state(pg_conn, attempt_id, "RUNNING")

    alloc_0 = AllocationService.create_allocation(
        pg_conn,
        allocation_id=f"alloc-0-{uuid.uuid4().hex[:6]}",
        attempt_id=attempt_id,
        node_id=node_0,
        device="cpu",
    )
    alloc_1 = AllocationService.create_allocation(
        pg_conn,
        allocation_id=f"alloc-1-{uuid.uuid4().hex[:6]}",
        attempt_id=attempt_id,
        node_id=node_1,
        device="cpu",
    )

    sess_id_0 = int(uuid.uuid4().hex[:8], 16)
    sess_id_1 = int(uuid.uuid4().hex[:8], 16)

    # Simulate Runtime emitting StateSnapshot with identity mapping
    snapshot_msg = StateSnapshot.from_dict({
        "runtime_instance_id": "rt-snap-1",
        "active_job_id": job_id,
        "active_attempt_id": attempt_id,
        "attempt_state": "RUNNING",
        "training_strategy": "strict_bsp",
        "checkpoint_policy": "every_step",
        "epoch": 1,
        "current_operation_id": 1,
        "current_batch_ordinal": 5,
        "model_version": 1,
        "workers": [
            {
                "worker_id": 0,
                "session_id": str(sess_id_0),
                "node_label": "worker-0",
                "protocol_version": 1,
                "connected_at": "2026-09-25T00:00:00Z",
                "state": "READY",
                "last_heartbeat_at": "2026-09-25T00:00:00Z",
                "shard_id": 0,
                "local_model_version": 1,
                "node_id": node_0,
                "allocation_id": alloc_0["allocation_id"],
            },
            {
                "worker_id": 1,
                "session_id": str(sess_id_1),
                "node_label": "worker-1",
                "protocol_version": 1,
                "connected_at": "2026-09-25T00:00:00Z",
                "state": "READY",
                "last_heartbeat_at": "2026-09-25T00:00:00Z",
                "shard_id": 1,
                "local_model_version": 1,
                "node_id": node_1,
                "allocation_id": alloc_1["allocation_id"],
            },
        ],
        "strategy_state": {},
        "checkpoint_state": "IDLE",
        "latest_checkpoint_id": None,
        "recovery_cursor": {},
        "dataset_build_id": "bld-1",
        "dataset_manifest_hash": f"hash-{job_id}",
        "last_runtime_event_seq": 10,
        "management_event_gap_count": 0,
        "captured_at": "2026-09-25T00:00:01Z",
    })

    # Process snapshot through RuntimeGateway
    gateway = RuntimeGateway()
    gateway.handle_state_snapshot(snapshot_msg)

    # 1. Verify mapping in PostgreSQL worker_sessions
    sessions = worker_session_repository.get_sessions_for_attempt(pg_conn, attempt_id)
    assert len(sessions) == 2
    sess_map = {s["worker_id"]: s for s in sessions}

    assert sess_map[0]["allocation_id"] == alloc_0["allocation_id"]
    assert sess_map[0]["node_id"] == node_0
    assert sess_map[0]["state"] == "READY"

    assert sess_map[1]["allocation_id"] == alloc_1["allocation_id"]
    assert sess_map[1]["node_id"] == node_1
    assert sess_map[1]["state"] == "READY"

    # 2. Verify backend recovery:
    # Simulating backend process restart where in-memory gateway has no snapshot,
    # get_attempt_snapshot reads authoritative projection from PostgreSQL
    fresh_gw = RuntimeGateway()
    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=fresh_gw):
        restored_snapshot = attempt_service.get_attempt_snapshot(pg_conn, attempt_id)
    assert restored_snapshot["attempt_id"] == attempt_id
    restored_workers = restored_snapshot["workers"]
    assert len(restored_workers) == 2

    restored_map = {w["worker_id"]: w for w in restored_workers}
    assert restored_map[0]["allocation_id"] == alloc_0["allocation_id"]
    assert restored_map[0]["node_id"] == node_0
    assert restored_map[1]["allocation_id"] == alloc_1["allocation_id"]
    assert restored_map[1]["node_id"] == node_1

    # 3. Verify list_attempt_workers
    workers_list = attempt_service.list_attempt_workers(pg_conn, attempt_id)
    assert len(workers_list) == 2
    assert {w["worker_id"] for w in workers_list} == {0, 1}
    assert {w["allocation_id"] for w in workers_list} == {
        alloc_0["allocation_id"],
        alloc_1["allocation_id"],
    }
