"""Phase 1 Backend Tests — Safe Abort Attempt Lifecycle Handling.

Verifies:
1. Runtime accepts Abort command (SUCCEEDED) but attempt is NOT terminated prematurely; remains active.
2. Receiving attempt.state_changed with ABORTED transitions attempt to ABORTED and cleans up allocations.
3. Duplicate terminal state_changed events are idempotent (no re-cleanup, no overwrite of ended_at).
4. Runtime rejects Abort command (REJECTED) -> raises CommandRejectedError (409), command state REJECTED, attempt unchanged.
5. Runtime unavailable or timeout triggers safe force-abort (_force_abort_attempt) with OPERATOR_ABORTED_DISCONNECTED_RUNTIME.
6. DB transaction error during state transition or abort rolls back cleanly without partial writes.
7. Multiple abort requests with the same Idempotency-Key return cached 202 response without re-dispatching.
8. Allocation cleanup strictly isolates to the target attempt without affecting other attempts' allocations.
9. Launching a new attempt is blocked (409 ACTIVE_ATTEMPT_EXISTS) while the aborting attempt is still active.
10. Once the attempt is authoritatively ABORTED and allocations cleaned, creating a new attempt succeeds.
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import psycopg
import pytest

from pbl4.management_backend import db
from pbl4.management_backend.gateways.runtime_gateway import (
    RuntimeGateway,
    RuntimeUnavailableError,
    get_gateway,
)
from pbl4.management_backend.repositories import (
    allocation_repository,
    attempt_repository,
    command_repository,
    job_repository,
)
from pbl4.management_backend.services import allocation_service, attempt_service
from pbl4.management_backend.services.allocation_service import AllocationService
from pbl4.management_backend.services.attempt_service import (
    AttemptConflictError,
    CommandRejectedError,
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
    """Ensure no leftover active attempts, jobs, allocations, or uncommitted transactions."""
    with suppress(Exception):
        pg_conn.rollback()
    with pg_conn.cursor() as cur:
        # Mark any leftover active attempts terminal
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
    job_id = f"job-abort-{uuid.uuid4().hex[:8]}"
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
                "Safe Abort Test Description",
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
            node_id = f"node-abort-{job_id}-{i}"
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


def _create_running_attempt(conn: psycopg.Connection, job_id: str) -> str:
    attempt_id = f"att-abort-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO attempts (
                attempt_id, job_id, state, execution_mode, contract_hash, created_at, started_at
            ) VALUES (%s, %s, 'RUNNING', 'FRESH', %s, %s, %s)
            """,
            (attempt_id, job_id, f"hash-{job_id}", now, now),
        )
    conn.commit()
    return attempt_id


# ─── 1. Runtime chấp nhận lệnh Abort nhưng attempt chưa có xác nhận kết thúc ─


def test_1_runtime_accepts_abort_leaves_attempt_active_and_command_succeeded(pg_conn):
    """Runtime accepts ABORT_ATTEMPT command; command row is SUCCEEDED, attempt remains RUNNING."""
    job_id = _create_ready_job(pg_conn)
    attempt_id = _create_running_attempt(pg_conn, job_id)
    idemp_key = f"key-abort-1-{uuid.uuid4().hex[:8]}"

    gw = get_gateway()
    # Mock Runtime accepting the command (initiation acknowledged, message="Abort requested.")
    with patch.object(
        gw,
        "send_command_and_wait_result",
        return_value={
            "command_id": "mock-cmd-id",
            "state": "SUCCEEDED",
            "result": {
                "result_code": "ABORTED",
                "message": "Abort requested.",
                "attempt_id": attempt_id,
            },
        },
    ):
        cmd_row = attempt_service.execute_abort_attempt(
            db,
            attempt_id=attempt_id,
            reason="Operator requested abort",
            idempotency_key=idemp_key,
        )

    # 1. Command record is SUCCEEDED with completed_at populated
    assert cmd_row["state"] == "SUCCEEDED"
    assert cmd_row["command_state"] == "SUCCEEDED"
    command_in_db = command_repository.get_command(pg_conn, cmd_row["command_id"])
    assert command_in_db is not None
    assert command_in_db["state"] == "SUCCEEDED"
    assert command_in_db["completed_at"] is not None

    # 2. Attempt record in DB MUST REMAIN RUNNING (NOT ABORTED!)
    attempt_in_db = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert attempt_in_db is not None
    assert attempt_in_db["state"] == "RUNNING"
    assert attempt_in_db["ended_at"] is None

    # 3. Starting a new attempt must be rejected with 409 ACTIVE_ATTEMPT_EXISTS
    with pytest.raises(AttemptConflictError) as exc_info:
        attempt_service.start_job(pg_conn, job_id)
    assert exc_info.value.code == "ACTIVE_ATTEMPT_EXISTS"
    assert attempt_id in str(exc_info.value)


# ─── 2. Nhận sự kiện attempt.state_changed với trạng thái ABORTED ────────────


def test_2_terminal_state_changed_event_transitions_attempt_to_aborted(pg_conn):
    """When attempt.state_changed (ABORTED) arrives, attempt transitions to ABORTED and allocations clean up."""
    job_id = _create_ready_job(pg_conn)
    attempt_id = _create_running_attempt(pg_conn, job_id)
    now = datetime.now(UTC)

    # Create an active allocation
    alloc_id = f"alloc-{uuid.uuid4().hex[:8]}"
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO worker_allocations (
                allocation_id, attempt_id, node_id, desired_state, actual_state,
                device, runtime_endpoint, created_at
            ) VALUES (%s, %s, %s, 'RUNNING', 'STARTED', 'cpu', 'localhost:50051', %s)
            """,
            (alloc_id, attempt_id, f"node-abort-{job_id}-0", now),
        )
    pg_conn.commit()

    # Project the terminal state transition
    terminal_time = now + timedelta(seconds=2)
    updated = RuntimeGateway._project_attempt_state_transition(
        pg_conn,
        attempt_id,
        "ABORTED",
        occurred_at=terminal_time,
        failure_code="OPERATOR_ABORTED",
        failure_message="Runtime completed abort sequence",
    )
    pg_conn.commit()

    assert updated is not None
    assert updated["state"] == "ABORTED"
    assert updated["ended_at"] is not None
    assert updated["failure_code"] == "OPERATOR_ABORTED"

    # Allocation must have desired_state set to STOPPED
    alloc = allocation_repository.get_allocation(pg_conn, alloc_id)
    assert alloc is not None
    assert alloc["desired_state"] == "STOPPED"


# ─── 3. Nhận sự kiện kết thúc trùng lặp ──────────────────────────────────────


def test_3_duplicate_terminal_event_is_idempotent(pg_conn):
    """Subsequent terminal event does not re-clean allocations or overwrite ended_at."""
    job_id = _create_ready_job(pg_conn)
    attempt_id = _create_running_attempt(pg_conn, job_id)
    t1 = datetime(2026, 10, 18, 12, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 10, 18, 12, 5, 0, tzinfo=UTC)

    # Initial transition to ABORTED
    RuntimeGateway._project_attempt_state_transition(
        pg_conn,
        attempt_id,
        "ABORTED",
        occurred_at=t1,
        failure_code="OPERATOR_ABORTED",
        failure_message="First abort event",
    )
    pg_conn.commit()

    attempt_after_first = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert attempt_after_first["state"] == "ABORTED"
    first_ended_at = attempt_after_first["ended_at"]

    # Replay/duplicate event arrives with t2 > t1
    with patch.object(
        AllocationService, "cleanup_allocations_for_attempt"
    ) as mock_cleanup:
        dup_updated = RuntimeGateway._project_attempt_state_transition(
            pg_conn,
            attempt_id,
            "ABORTED",
            occurred_at=t2,
            failure_code="REPLAY_ABORT",
            failure_message="Duplicate event",
        )
        pg_conn.commit()

        # Cleanup allocations MUST NOT be called again
        mock_cleanup.assert_not_called()

    # ended_at MUST NOT be overwritten
    attempt_after_dup = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert attempt_after_dup["ended_at"] == first_ended_at
    assert attempt_after_dup["failure_code"] == "OPERATOR_ABORTED"


# ─── 4. Runtime từ chối Abort ────────────────────────────────────────────────


def test_4_runtime_rejects_abort_command(pg_conn):
    """Runtime rejects ABORT_ATTEMPT command; raises CommandRejectedError, command REJECTED, attempt unchanged."""
    job_id = _create_ready_job(pg_conn)
    attempt_id = _create_running_attempt(pg_conn, job_id)
    idemp_key = f"key-abort-4-{uuid.uuid4().hex[:8]}"

    gw = get_gateway()
    with patch.object(
        gw,
        "send_command_and_wait_result",
        return_value={
            "command_id": "mock-rej-cmd",
            "state": "REJECTED",
            "result": {
                "result_code": "ATTEMPT_NOT_ABORTABLE",
                "message": "Attempt already completing",
            },
        },
    ):
        with pytest.raises(CommandRejectedError) as exc_info:
            attempt_service.execute_abort_attempt(
                db,
                attempt_id=attempt_id,
                reason="Abort attempt",
                idempotency_key=idemp_key,
            )

    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "ATTEMPT_NOT_ABORTABLE"

    # Command row in DB is REJECTED
    command_in_db = command_repository.get_command(pg_conn, exc_info.value.command_id)
    assert command_in_db is not None
    assert command_in_db["state"] == "REJECTED"

    # Attempt in DB is STILL RUNNING
    attempt_in_db = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert attempt_in_db["state"] == "RUNNING"
    assert attempt_in_db["ended_at"] is None


# ─── 5. Runtime không khả dụng hoặc timeout ──────────────────────────────────


def test_5_runtime_unavailable_or_timeout_triggers_force_abort(pg_conn):
    """When Runtime is disconnected/unavailable, execute_abort_attempt safely force-aborts in DB."""
    job_id = _create_ready_job(pg_conn)
    attempt_id = _create_running_attempt(pg_conn, job_id)
    idemp_key = f"key-abort-5-{uuid.uuid4().hex[:8]}"

    # Add an active allocation to verify cleanup
    alloc_id = f"alloc-5-{uuid.uuid4().hex[:8]}"
    now = datetime.now(UTC)
    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO worker_allocations (
                allocation_id, attempt_id, node_id, desired_state, actual_state,
                device, runtime_endpoint, created_at
            ) VALUES (%s, %s, %s, 'RUNNING', 'STARTED', 'cpu', 'localhost:50051', %s)
            """,
            (alloc_id, attempt_id, f"node-abort-{job_id}-0", now),
        )
    pg_conn.commit()

    gw = get_gateway()
    with patch.object(
        gw,
        "send_command_and_wait_result",
        side_effect=RuntimeUnavailableError("Runtime daemon unreachable"),
    ):
        cmd_row = attempt_service.execute_abort_attempt(
            db,
            attempt_id=attempt_id,
            reason="Emergency abort",
            idempotency_key=idemp_key,
        )

    # Force abort sets command state to SUCCEEDED (force aborted)
    assert cmd_row["state"] == "SUCCEEDED"

    # Attempt in DB is safely transitioned to ABORTED with OPERATOR_ABORTED_DISCONNECTED_RUNTIME
    attempt_in_db = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert attempt_in_db["state"] == "ABORTED"
    assert attempt_in_db["ended_at"] is not None
    assert attempt_in_db["failure_code"] == "OPERATOR_ABORTED_DISCONNECTED_RUNTIME"

    # Allocation desired_state is set to STOPPED
    alloc = allocation_repository.get_allocation(pg_conn, alloc_id)
    assert alloc["desired_state"] == "STOPPED"


# ─── 6. Transaction cập nhật trạng thái gặp lỗi ─────────────────────────────


def test_6_database_transaction_error_rolls_back(pg_conn):
    """Database error during projection or execution causes clean rollback without dirty partial state."""
    job_id = _create_ready_job(pg_conn)
    attempt_id = _create_running_attempt(pg_conn, job_id)
    now = datetime.now(UTC)

    with patch.object(
        allocation_repository,
        "list_for_attempt",
        side_effect=psycopg.OperationalError("Simulated DB connection glitch"),
    ):
        with pytest.raises(psycopg.OperationalError):
            with pg_conn.transaction():
                attempt_repository.update_attempt_state(
                    pg_conn,
                    attempt_id,
                    "ABORTED",
                    ended_at=now,
                )
                # Cleanup raises error
                allocation_service.cleanup_allocations_for_attempt(pg_conn, attempt_id)

    # Transaction was rolled back: attempt state remains RUNNING
    attempt_in_db = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert attempt_in_db["state"] == "RUNNING"
    assert attempt_in_db["ended_at"] is None


# ─── 7. Gửi nhiều yêu cầu Abort với cùng idempotency key ──────────────────────


def test_7_multiple_abort_requests_with_same_idempotency_key(pg_conn):
    """Repeating abort with identical Idempotency-Key returns cached response without second dispatch."""
    job_id = _create_ready_job(pg_conn)
    attempt_id = _create_running_attempt(pg_conn, job_id)
    idemp_key = f"key-abort-7-{uuid.uuid4().hex[:8]}"

    gw = get_gateway()
    dispatch_mock = MagicMock(
        return_value={
            "command_id": "cmd-idemp-7",
            "state": "SUCCEEDED",
            "result": {
                "result_code": "ABORTED",
                "message": "Abort requested.",
                "attempt_id": attempt_id,
            },
        }
    )

    with patch.object(gw, "send_command_and_wait_result", dispatch_mock):
        res1 = attempt_service.execute_abort_attempt(
            db,
            attempt_id=attempt_id,
            reason="First try",
            idempotency_key=idemp_key,
        )
        res2 = attempt_service.execute_abort_attempt(
            db,
            attempt_id=attempt_id,
            reason="First try",
            idempotency_key=idemp_key,
        )

    # Dispatched to runtime exactly ONCE
    assert dispatch_mock.call_count == 1
    # Both responses refer to the exact same command_id
    assert res1["command_id"] == res2["command_id"]
    assert res1["state"] == "SUCCEEDED"


# ─── 8. Allocation của attempt khác không bị ảnh hưởng ───────────────────────


def test_8_allocation_cleanup_isolation_other_attempts_unaffected(pg_conn):
    """cleanup_allocations_for_attempt on Attempt A does not modify Attempt B's allocations."""
    job_id_a = _create_ready_job(pg_conn, display_name="Job A")
    job_id_b = _create_ready_job(pg_conn, display_name="Job B")

    now = datetime.now(UTC)
    att_a = f"att-iso-a-{uuid.uuid4().hex[:8]}"
    att_b = f"att-iso-b-{uuid.uuid4().hex[:8]}"

    with pg_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO attempts (attempt_id, job_id, state, execution_mode, contract_hash, created_at)
            VALUES (%s, %s, 'RUNNING', 'FRESH', 'hash-a', %s)
            """,
            (att_a, job_id_a, now),
        )
        cur.execute(
            """
            INSERT INTO attempts (attempt_id, job_id, state, execution_mode, contract_hash, created_at)
            VALUES (%s, %s, 'FAILED', 'FRESH', 'hash-b', %s)
            """,
            (att_b, job_id_b, now),
        )
        # Allocation A
        cur.execute(
            """
            INSERT INTO worker_allocations (
                allocation_id, attempt_id, node_id, desired_state, actual_state,
                device, runtime_endpoint, created_at
            ) VALUES (%s, %s, %s, 'RUNNING', 'STARTED', 'cpu', 'localhost:50051', %s)
            """,
            (f"alloc-a-{att_a}", att_a, f"node-abort-{job_id_a}-0", now),
        )
        # Allocation B
        cur.execute(
            """
            INSERT INTO worker_allocations (
                allocation_id, attempt_id, node_id, desired_state, actual_state,
                device, runtime_endpoint, created_at
            ) VALUES (%s, %s, %s, 'RUNNING', 'STARTED', 'cpu', 'localhost:50051', %s)
            """,
            (f"alloc-b-{att_b}", att_b, f"node-abort-{job_id_b}-0", now),
        )
    pg_conn.commit()

    # Clean allocations for Attempt A only
    AllocationService.cleanup_allocations_for_attempt(pg_conn, att_a)
    pg_conn.commit()

    # Verify Attempt A allocation is STOPPED
    alloc_a = allocation_repository.get_allocation(pg_conn, f"alloc-a-{att_a}")
    assert alloc_a["desired_state"] == "STOPPED"

    # Verify Attempt B allocation is UNTOUCHED (still RUNNING/STARTED)
    alloc_b = allocation_repository.get_allocation(pg_conn, f"alloc-b-{att_b}")
    assert alloc_b["desired_state"] == "RUNNING"
    assert alloc_b["actual_state"] == "STARTED"


# ─── 9. Không cho phép tạo attempt mới khi attempt cũ vẫn thực sự active ─────


def test_9_cannot_create_new_attempt_while_aborting_attempt_still_active(pg_conn):
    """While an attempt is active (e.g. abort command sent but not yet stopped), starting new attempt is blocked."""
    job_id = _create_ready_job(pg_conn)
    attempt_id = _create_running_attempt(pg_conn, job_id)

    # get_active_attempt detects the active attempt
    active = attempt_repository.get_active_attempt(pg_conn)
    assert active is not None
    assert active["attempt_id"] == attempt_id

    # start_job rejects with ACTIVE_ATTEMPT_EXISTS
    with pytest.raises(AttemptConflictError) as exc_info:
        attempt_service.start_job(pg_conn, job_id)
    assert exc_info.value.code == "ACTIVE_ATTEMPT_EXISTS"

    # retry_job also rejects with ACTIVE_ATTEMPT_EXISTS
    with pytest.raises(AttemptConflictError) as exc_info_retry:
        attempt_service.retry_job(pg_conn, job_id)
    assert exc_info_retry.value.code == "ACTIVE_ATTEMPT_EXISTS"


# ─── 10. Sau khi attempt kết thúc hợp lệ, không bị chặn tạo attempt tiếp theo ─


def test_10_can_create_new_attempt_after_attempt_reaches_aborted(pg_conn):
    """Once an attempt reaches ABORTED and allocations are cleaned, starting a new attempt succeeds."""
    job_id = _create_ready_job(pg_conn)
    attempt_1 = _create_running_attempt(pg_conn, job_id)
    now = datetime.now(UTC)

    # Transition Attempt 1 to terminal ABORTED
    RuntimeGateway._project_attempt_state_transition(
        pg_conn,
        attempt_1,
        "ABORTED",
        occurred_at=now,
        failure_code="OPERATOR_ABORTED",
        failure_message="Abort completed successfully",
    )
    pg_conn.commit()

    # Invariant: No active attempt exists anymore
    active = attempt_repository.get_active_attempt(pg_conn)
    assert active is None

    # Starting a new attempt must now succeed without 409 or unique index violation
    attempt_2_row, cmd_row = attempt_service.start_job(pg_conn, job_id)
    pg_conn.commit()

    assert attempt_2_row is not None
    assert attempt_2_row["attempt_id"] != attempt_1
    assert attempt_2_row["state"] == "CREATED"
    assert cmd_row["command_type"] == "START_ATTEMPT"
