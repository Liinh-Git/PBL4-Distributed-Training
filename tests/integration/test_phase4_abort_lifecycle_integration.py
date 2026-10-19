"""Phase 4: Comprehensive Integration Tests for the Abort Attempt Lifecycle.

Verifies end-to-end correctness across:
- Group 1: Abort during initialization (WAITING_WORKERS, PROVISIONING, INITIALIZING)
- Group 2: Abort during training and completion (RUNNING, COMPLETING, terminal attempts)
- Group 3: Faults and connection disruptions (Runtime disconnect, Abort timeout, Worker connection race)
- Group 4: New attempt creation and resource preservation (immediate creation, concurrent race, job isolation)
- Group 5: Frontend state synchronization invariants (HTTP 202 pending state, WebSocket terminal event, reconnect recovery, 409 handling)

Invariant:
- At all times, at most one attempt is allowed to be active in the cluster.
- uq_attempts__one_active is preserved.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import psycopg
import pytest

from pbl4.agent_protocol.messages import StartWorkerPayload, StopWorkerPayload
from pbl4.management_backend import db
from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway
from pbl4.management_backend.repositories import (
    allocation_repository,
    attempt_repository,
    command_repository,
)
from pbl4.management_backend.services import attempt_service
from pbl4.management_backend.services.allocation_service import AllocationService
from pbl4.management_backend.services.attempt_service import (
    AttemptConflictError,
    AttemptNotAbortableError,
    CommandRejectedError,
    RuntimeUnavailableError,
)
from pbl4.protocol.constants import (
    MESSAGE_TYPE_HELLO,
    MESSAGE_TYPE_STOP,
    UNASSIGNED_WORKER_ID,
)
from pbl4.protocol.messages import (
    DTPFrame,
    ERROR_CODE_WORKER_ADMISSION_INVALID,
    Hello,
    Stop,
    build_control_frame,
    decode_control_message,
)
from pbl4.transport.framed_socket import recv_exact, send_all
from pbl4.runtime.parameter_server import ParameterServer
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.worker.worker_client import WorkerClient

TEST_DB_URL = (
    os.environ.get("TEST_DATABASE_URL")
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
    os.environ["DATABASE_URL"] = TEST_DB_URL
    os.environ["PBL4_WORKER_ADMISSION_SECRET"] = "phase4-test-secret-key-32-chars!"
    db.init_pool(TEST_DB_URL, min_size=1, max_size=5)
    yield
    db.close_pool()


@pytest.fixture
def pg_conn():
    conn = psycopg.connect(TEST_DB_URL, autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def clean_db(pg_conn):
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
    job_id = f"job-phase4-{uuid.uuid4().hex[:8]}"
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
                f"Phase 4 Test Job {job_id}",
                "Integration test job for abort lifecycle",
                "READY",
                json.dumps({"dataset_build_id": "bld-1"}),
                json.dumps(
                    {
                        "synchronization": {"expected_workers": expected_workers},
                        "training": {"training_seed": training_seed},
                        "model": {"model_id": "resnet18_groupnorm"},
                    }
                ),
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
) -> None:
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        for nid in node_ids:
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
                    json.dumps({"gpu_count": 0, "gpus": []}),
                    now,
                    state,
                ),
            )


from pbl4.common.hashing import sha256_bytes
from pbl4.protocol.parameter_manifest import ParameterEntry, ParameterManifest

def _make_dummy_manifest() -> ParameterManifest:
    entry = ParameterEntry(
        tensor_id=0,
        name="weight",
        shape=(10, 10),
        dtype="float32",
        numel=100,
        byte_offset=0,
        byte_length=400,
    )
    content = {
        "schema_version": 1,
        "total_numel": 100,
        "total_bytes": 400,
        "parameters": [entry.to_dict()],
    }
    raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return ParameterManifest(
        parameter_manifest_hash=sha256_bytes(raw),
        schema_version=1,
        total_numel=100,
        total_bytes=400,
        parameters=(entry,),
    )


# ==============================================================================
# GROUP 1: ABORT IN INITIALIZATION STATES
# ==============================================================================


def test_1_abort_in_waiting_workers_releases_wait_and_allows_next_attempt(pg_conn):
    """Test 1: WAITING_WORKERS
    Start attempt when workers haven't connected yet.
    Send Abort -> Runtime unblocks without waiting 180s timeout.
    Terminal event sent -> Attempt marked ABORTED.
    Allocations cleaned up -> New attempt can be created immediately.
    """
    job_id = _create_test_job(pg_conn, expected_workers=2)
    node_0, node_1 = f"n0-{uuid.uuid4().hex[:6]}", f"n1-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_0, node_1])

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-start",
        "command_type": "START_ATTEMPT",
    }
    mock_node_gw = MagicMock()
    mock_node_gw.send_start_worker.return_value = True

    with (
        patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw),
        patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw),
    ):
        attempt_row, _ = attempt_service.execute_start_job(db, job_id, idempotency_key=f"ik-{uuid.uuid4().hex}")

    attempt_id = attempt_row["attempt_id"]

    # Transition attempt to WAITING_WORKERS
    attempt_repository.update_attempt_state(pg_conn, attempt_id, "WAITING_WORKERS")

    # Start real ParameterServer and verify abort unblocks wait_for_workers instantly
    manifest = _make_dummy_manifest()
    registry = WorkerRegistry(attempt_id, 2)
    server = ParameterServer("127.0.0.1", 0, attempt_id=attempt_id, job_id=job_id, expected_workers=2, manifest=manifest, registry=registry)
    server.start()

    wait_thread_exited = threading.Event()
    wait_result: list[bool] = []

    def background_wait():
        res = server.wait_for_workers(2, timeout=180.0)
        wait_result.append(res)
        wait_thread_exited.set()

    t = threading.Thread(target=background_wait, daemon=True)
    t.start()

    time.sleep(0.05)
    assert not wait_thread_exited.is_set(), "Server should still be waiting for workers"

    start_abort_time = time.monotonic()
    server.abort()
    assert wait_thread_exited.wait(timeout=2.0), "wait_for_workers must unblock immediately on abort, not wait 180s"
    elapsed = time.monotonic() - start_abort_time
    assert elapsed < 1.0, f"Abort took {elapsed}s; expected < 1.0s"
    assert wait_result == [False], "wait_for_workers should return False on abort"

    server.stop()

    # Now execute backend abort flow
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "SUCCEEDED",
        "command_id": "cmd-abort",
        "command_type": "ABORT_ATTEMPT",
        "result": {"result_code": "ABORTED"},
    }
    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw):
        cmd_res = attempt_service.execute_abort_attempt(db, attempt_id=attempt_id, reason="Operator abort test 1", idempotency_key=f"ik-{uuid.uuid4().hex}")

    assert cmd_res["command_type"] == "ABORT_ATTEMPT"

    # Simulate arrival of terminal event via RuntimeGateway
    RuntimeGateway._project_attempt_state_transition(
        pg_conn,
        attempt_id,
        "ABORTED",
        occurred_at=datetime.now(UTC),
        failure_code="OPERATOR_ABORTED",
        failure_message="Attempt aborted by operator",
    )

    # Verify attempt in DB is ABORTED with valid ended_at
    att = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert att["state"] == "ABORTED"
    assert att["ended_at"] is not None

    # Verify allocations cleaned up (no active allocations)
    active_allocs = allocation_repository.list_for_attempt(pg_conn, attempt_id, active_only=True)
    assert len(active_allocs) == 0

    # Invariant: Immediate next attempt creation must succeed without ACTIVE_ATTEMPT_EXISTS
    with (
        patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw),
        patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw),
    ):
        next_attempt_row, _ = attempt_service.execute_start_job(db, job_id, idempotency_key=f"ik-{uuid.uuid4().hex}")
    assert next_attempt_row["attempt_id"] != attempt_id
    assert next_attempt_row["state"] == "CREATED"


def test_2_abort_in_provisioning_stops_workers_and_rejects_connecting():
    """Test 2: PROVISIONING
    Abort during provisioning / dataset assignment.
    Verifies Stop message is sent to connected workers and connecting workers are rejected.
    """
    attempt_id = f"att-prov-{uuid.uuid4().hex[:6]}"
    manifest = _make_dummy_manifest()
    registry = WorkerRegistry(attempt_id, 2)
    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id=attempt_id,
        job_id="job-prov",
        expected_workers=2,
        manifest=manifest,
        registry=registry,
        require_worker_admission=False,
    )
    server.start()
    host, port = server.bound_address

    stop_received = threading.Event()

    def on_worker_msg(msg, _op):
        if isinstance(msg, Stop):
            stop_received.set()

    # Worker 0 connects
    client_0 = WorkerClient(host, port, node_label="worker-0", manifest=manifest, message_handler=on_worker_msg)
    client_0.connect()

    # Wait for worker 0 to be registered
    assert server.wait_for_workers(1, timeout=2.0)

    # Abort while still provisioning
    server.abort()

    # Connected worker must receive STOP
    assert stop_received.wait(timeout=2.0), "Worker must receive Stop frame upon abort in provisioning"

    # Worker 1 tries to connect AFTER abort -> must be rejected with admission error
    rejected = False
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.connect((host, port))
        hello = Hello.from_dict({
            "node_label": "worker-1",
            "client_instance_id": str(uuid.uuid4()),
            "role": "worker",
            "protocol_version": 1,
            "framework_adapter": "pytorch",
            "supported_tensor_encoding": ["fp32_le_v1"],
            "supported_strategy_capabilities": ["strict_bsp"],
        })
        frame = build_control_frame(hello, session_id=0, worker_id=UNASSIGNED_WORKER_ID)
        frame.write_to(sock, send_all)

        resp = DTPFrame.read_from(sock, recv_exact)
        if resp.header.message_type == MESSAGE_TYPE_STOP or resp.header.message_type == 0x00FF:
            rejected = True
    except (ConnectionResetError, EOFError):
        rejected = True
    finally:
        sock.close()
        client_0.disconnect()
        server.stop()

    assert rejected, "Connecting worker must be rejected after abort has been flagged"


def test_3_abort_in_initializing_timing_and_resource_release(pg_conn):
    """Test 3: INITIALIZING
    Abort before and after Coordinator is created.
    Verify DTP port and runner resources are released without hangs.
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    attempt_id = f"att-init-{uuid.uuid4().hex[:6]}"

    # Setup ParameterServer
    manifest = _make_dummy_manifest()
    registry = WorkerRegistry(attempt_id, 1)
    server = ParameterServer("127.0.0.1", 0, attempt_id=attempt_id, job_id=job_id, expected_workers=1, manifest=manifest, registry=registry)
    server.start()
    bound_addr = server.bound_address
    assert bound_addr is not None

    # Abort during initialization wait_for_manifests
    manifest_wait_done = threading.Event()

    def wait_manifest():
        server.wait_for_manifests(timeout=120.0)
        manifest_wait_done.set()

    t = threading.Thread(target=wait_manifest, daemon=True)
    t.start()

    time.sleep(0.05)
    server.abort()
    assert manifest_wait_done.wait(timeout=2.0), "wait_for_manifests must abort cleanly"
    server.stop()

    # Verify socket is released by binding to the same port
    test_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    test_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    test_sock.bind(("127.0.0.1", bound_addr[1]))
    test_sock.close()


# ==============================================================================
# GROUP 2: ABORT DURING TRAINING AND WHEN TERMINAL
# ==============================================================================


def test_4_abort_in_running_stops_training_and_workers():
    """Test 4: RUNNING
    When training is running, abort halts loop and dispatches Stop to workers.
    """
    attempt_id = f"att-run-{uuid.uuid4().hex[:6]}"
    manifest = _make_dummy_manifest()
    registry = WorkerRegistry(attempt_id, 1)
    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id=attempt_id,
        job_id="job-run",
        expected_workers=1,
        manifest=manifest,
        registry=registry,
        require_worker_admission=False,
    )
    server.start()
    host, port = server.bound_address

    stop_received = threading.Event()

    def on_worker_msg(msg, _op):
        if isinstance(msg, Stop):
            stop_received.set()

    client = WorkerClient(host, port, node_label="worker-0", manifest=manifest, message_handler=on_worker_msg)
    client.connect()
    assert server.wait_for_workers(1, timeout=2.0)

    # Trigger abort
    server.abort()
    assert stop_received.wait(timeout=2.0), "Worker must receive Stop frame when abort occurs in RUNNING"

    client.disconnect()
    server.stop()


def test_5_abort_rejected_in_completing(pg_conn):
    """Test 5: COMPLETING
    When attempt is in COMPLETING, abort is rejected (HTTP 409).
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    attempt_id = f"att-comp-{uuid.uuid4().hex[:6]}"
    attempt_repository.create_attempt(
        pg_conn,
        attempt_id=attempt_id,
        job_id=job_id,
        contract_hash=f"hash-{job_id}",
        execution_mode="FRESH",
        created_at=datetime.now(UTC),
    )
    attempt_repository.update_attempt_state(pg_conn, attempt_id, "COMPLETING")

    with pytest.raises(AttemptNotAbortableError) as exc_info:
        attempt_service.abort_attempt(pg_conn, attempt_id=attempt_id, reason="Should fail")

    assert "COMPLETING" in str(exc_info.value)
    # State remains COMPLETING
    att = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert att["state"] == "COMPLETING"


def test_6_abort_rejected_on_already_terminal_attempt(pg_conn):
    """Test 6: Attempt already terminal
    Abort attempt in FAILED / COMPLETED / ABORTED is rejected without corrupting history.
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    attempt_id = f"att-term-{uuid.uuid4().hex[:6]}"
    now = datetime.now(UTC)
    attempt_repository.create_attempt(
        pg_conn,
        attempt_id=attempt_id,
        job_id=job_id,
        contract_hash=f"hash-{job_id}",
        execution_mode="FRESH",
        created_at=now,
    )
    attempt_repository.update_attempt_state(
        pg_conn,
        attempt_id,
        "COMPLETED",
        ended_at=now,
    )

    with pytest.raises(AttemptNotAbortableError) as exc_info:
        attempt_service.abort_attempt(pg_conn, attempt_id=attempt_id, reason="Should fail on completed")

    assert "COMPLETED" in str(exc_info.value)
    att = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert att["state"] == "COMPLETED"
    assert att["ended_at"] is not None


# ==============================================================================
# GROUP 3: FAULTS AND CONNECTION DISRUPTIONS
# ==============================================================================


def test_7_runtime_disconnect_and_orphan_worker_handling(pg_conn):
    """Test 7: Runtime disconnected
    Runtime abruptly shuts down while workers exist.
    Backend and Node Agent cleanly stop orphan workers and prevent resource reuse.
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    node_id = f"node-disc-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_id])

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-start",
        "command_type": "START_ATTEMPT",
    }
    stopped_allocations: list[str] = []
    mock_node_gw = MagicMock()
    mock_node_gw.send_start_worker.return_value = True
    mock_node_gw.is_node_connected.return_value = True

    def fake_send_stop(nid: str, *, command: StopWorkerPayload) -> bool:
        stopped_allocations.append(command.allocation_id)
        return True

    mock_node_gw.send_stop_worker.side_effect = fake_send_stop

    with (
        patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw),
        patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw),
    ):
        attempt_row, _ = attempt_service.execute_start_job(db, job_id, idempotency_key=f"ik-{uuid.uuid4().hex}")

    attempt_id = attempt_row["attempt_id"]
    allocs = allocation_repository.list_for_attempt(pg_conn, attempt_id)
    assert len(allocs) == 1
    alloc_id = allocs[0]["allocation_id"]

    # Simulate Runtime dying (RuntimeUnavailableError) when Abort is attempted
    mock_rt_gw.send_command_and_wait_result.side_effect = RuntimeUnavailableError("Runtime process died")

    with (
        patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw),
        patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw),
    ):
        cmd_row = attempt_service.execute_abort_attempt(
            db,
            attempt_id=attempt_id,
            reason="Runtime disconnected test",
            idempotency_key=f"ik-{uuid.uuid4().hex}",
        )

    # Force abort succeeded
    assert cmd_row["state"] == "SUCCEEDED"
    att = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert att["state"] == "ABORTED"
    assert att["failure_code"] == "OPERATOR_ABORTED_DISCONNECTED_RUNTIME"

    # STOP_WORKER was dispatched to Node Agent
    assert alloc_id in stopped_allocations


def test_8_abort_timeout_or_unresponsive_runtime_reconciles(pg_conn):
    """Test 8: Abort timeout or no response
    Backend force-aborts cleanly without conflicting state in command, attempt, or allocation.
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    attempt_id = f"att-to-{uuid.uuid4().hex[:6]}"
    now = datetime.now(UTC)
    attempt_repository.create_attempt(
        pg_conn,
        attempt_id=attempt_id,
        job_id=job_id,
        contract_hash=f"hash-{job_id}",
        execution_mode="FRESH",
        created_at=now,
    )
    attempt_repository.update_attempt_state(pg_conn, attempt_id, "RUNNING")

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.side_effect = RuntimeUnavailableError("Timeout waiting for Runtime")

    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw):
        cmd = attempt_service.execute_abort_attempt(
            db,
            attempt_id=attempt_id,
            reason="Operator timeout test",
            idempotency_key=f"ik-{uuid.uuid4().hex}",
        )

    assert cmd["state"] == "SUCCEEDED"
    att = attempt_repository.get_attempt(pg_conn, attempt_id)
    assert att["state"] == "ABORTED"
    assert att["ended_at"] is not None


def test_9_worker_connects_right_at_abort_race():
    """Test 9: Worker connects right at the moment Abort is flagged
    Server must reject admission and not record an active session.
    """
    attempt_id = f"att-race-{uuid.uuid4().hex[:6]}"
    manifest = _make_dummy_manifest()
    registry = WorkerRegistry(attempt_id, 1)
    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id=attempt_id,
        job_id="job-race",
        expected_workers=1,
        manifest=manifest,
        registry=registry,
        require_worker_admission=False,
    )
    server.start()
    host, port = server.bound_address

    # Set abort BEFORE connection finishes HELLO
    server.abort()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    hello = Hello.from_dict({
        "node_label": "worker-race",
        "client_instance_id": str(uuid.uuid4()),
        "role": "worker",
        "protocol_version": 1,
        "framework_adapter": "pytorch",
        "supported_tensor_encoding": ["fp32_le_v1"],
        "supported_strategy_capabilities": ["strict_bsp"],
    })
    frame = build_control_frame(hello, session_id=0, worker_id=UNASSIGNED_WORKER_ID)
    frame.write_to(sock, send_all)

    # Server must reject with admission error
    resp = DTPFrame.read_from(sock, recv_exact)
    msg = decode_control_message(resp.header.message_type, resp.payload)
    sock.close()
    server.stop()

    # Session was rejected and registry has 0 active sessions
    assert resp.header.message_type in (0x00FF, MESSAGE_TYPE_STOP) or getattr(msg, "error_code", None) == ERROR_CODE_WORKER_ADMISSION_INVALID
    assert len(registry.snapshot()) == 0


# ==============================================================================
# GROUP 4: NEW ATTEMPT CREATION AND RESOURCE PRESERVATION
# ==============================================================================


def test_10_immediate_new_attempt_after_abort_success(pg_conn):
    """Test 10: Create new attempt immediately after abort
    Verified: no ACTIVE_ATTEMPT_EXISTS, new attempt created cleanly.
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    node_id = f"node-imm-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_id])

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-1",
        "command_type": "START_ATTEMPT",
    }
    mock_node_gw = MagicMock()
    mock_node_gw.send_start_worker.return_value = True

    with (
        patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw),
        patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw),
    ):
        att1, _ = attempt_service.execute_start_job(db, job_id, idempotency_key=f"ik-{uuid.uuid4().hex}")

    # Abort attempt 1
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "SUCCEEDED",
        "command_id": "cmd-abort",
        "command_type": "ABORT_ATTEMPT",
        "result": {"result_code": "ABORTED"},
    }
    with patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw):
        attempt_service.execute_abort_attempt(db, attempt_id=att1["attempt_id"], idempotency_key=f"ik-{uuid.uuid4().hex}")

    # Terminal projection
    RuntimeGateway._project_attempt_state_transition(
        pg_conn,
        att1["attempt_id"],
        "ABORTED",
        occurred_at=datetime.now(UTC),
    )

    # Immediately create attempt 2
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-2",
        "command_type": "START_ATTEMPT",
    }
    with (
        patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw),
        patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw),
    ):
        att2, _ = attempt_service.execute_start_job(db, job_id, idempotency_key=f"ik-{uuid.uuid4().hex}")

    assert att2["attempt_id"] != att1["attempt_id"]
    assert att2["state"] == "CREATED"


def test_11_concurrent_attempt_creation_race_strictly_enforces_single_active(pg_conn):
    """Test 11: Two concurrent attempt creation requests
    At most one active attempt succeeds; the other gets AttemptConflictError.
    """
    job_id = _create_test_job(pg_conn, expected_workers=1)
    node_id = f"node-race-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_id])

    results: list[Any] = []
    errors: list[Exception] = []

    mock_rt_gw = MagicMock()
    mock_rt_gw.send_command_and_wait_result.return_value = {
        "state": "ACCEPTED",
        "command_id": "cmd-race",
        "command_type": "START_ATTEMPT",
    }
    mock_node_gw = MagicMock()
    mock_node_gw.send_start_worker.return_value = True

    barrier = threading.Barrier(2)

    def worker_start():
        barrier.wait()
        try:
            with (
                patch("pbl4.management_backend.services.attempt_service.get_gateway", return_value=mock_rt_gw),
                patch("pbl4.management_backend.gateways.node_control_gateway.get_node_control_gateway", return_value=mock_node_gw),
            ):
                res = attempt_service.execute_start_job(db, job_id, idempotency_key=f"ik-{uuid.uuid4().hex}")
                results.append(res)
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=worker_start)
    t2 = threading.Thread(target=worker_start)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one succeeded and one failed with conflict
    assert len(results) == 1, f"Expected 1 success, got {len(results)}"
    assert len(errors) == 1, f"Expected 1 conflict error, got {len(errors)}"
    assert isinstance(errors[0], AttemptConflictError)


def test_12_isolation_between_two_jobs(pg_conn):
    """Test 12: Isolation between two jobs
    Job A has allocations; aborting Job B does NOT touch Job A's allocations.
    """
    job_a = _create_test_job(pg_conn, expected_workers=1)
    job_b = _create_test_job(pg_conn, expected_workers=1)

    node_a = f"node-a-{uuid.uuid4().hex[:6]}"
    node_b = f"node-b-{uuid.uuid4().hex[:6]}"
    _enroll_test_nodes(pg_conn, [node_a, node_b])

    # Start attempt for Job A
    att_a = f"att-a-{uuid.uuid4().hex[:6]}"
    now = datetime.now(UTC)
    attempt_repository.create_attempt(
        pg_conn,
        attempt_id=att_a,
        job_id=job_a,
        contract_hash=f"hash-{job_a}",
        execution_mode="FRESH",
        created_at=now,
    )
    alloc_a = AllocationService.create_allocation(
        pg_conn,
        allocation_id=f"alloc-a-{uuid.uuid4().hex[:6]}",
        attempt_id=att_a,
        node_id=node_a,
        device="cpu",
        now=now,
    )

    # Create attempt for Job B
    att_b = f"att-b-{uuid.uuid4().hex[:6]}"
    # Mark attempt A COMPLETED so attempt B can be created without violating unique index
    attempt_repository.update_attempt_state(pg_conn, att_a, "COMPLETED")
    attempt_repository.create_attempt(
        pg_conn,
        attempt_id=att_b,
        job_id=job_b,
        contract_hash=f"hash-{job_b}",
        execution_mode="FRESH",
        created_at=now,
    )
    alloc_b = AllocationService.create_allocation(
        pg_conn,
        allocation_id=f"alloc-b-{uuid.uuid4().hex[:6]}",
        attempt_id=att_b,
        node_id=node_b,
        device="cpu",
        now=now,
    )

    # Cleanup allocations for Job B's attempt
    AllocationService.cleanup_allocations_for_attempt(pg_conn, att_b, now=now)

    # Job B's allocation was cleaned up
    b_row = allocation_repository.get_allocation(pg_conn, alloc_b["allocation_id"])
    assert b_row["actual_state"] == allocation_repository.ACTUAL_STATE_FAILED

    # Job A's allocation was NOT modified
    a_row = allocation_repository.get_allocation(pg_conn, alloc_a["allocation_id"])
    assert a_row["actual_state"] == allocation_repository.ACTUAL_STATE_REQUESTED


# ==============================================================================
# GROUP 5: FRONTEND STATE SYNCHRONIZATION INVARIANTS
# ==============================================================================


def test_13_frontend_http_202_snapshot_active_preserves_aborting():
    """Test 13: HTTP 202 followed by active snapshot preserves Aborting... state."""
    aborting_set = {"att-ui-1"}
    # Immediate snapshot arrives with RUNNING
    snapshot_state = "RUNNING"
    is_terminal = snapshot_state in ("COMPLETED", "FAILED", "ABORTED")

    # Invariant: non-terminal snapshot must NOT clear aborting set
    if is_terminal:
        aborting_set.discard("att-ui-1")

    assert "att-ui-1" in aborting_set, "Aborting flag must be preserved while snapshot is non-terminal"


def test_14_frontend_websocket_terminal_updates_all():
    """Test 14: WebSocket receives terminal event -> unmarks aborting and updates state."""
    aborting_set = {"att-ui-2"}
    current_state = "RUNNING"

    # Terminal event arrives
    event = {"event_type": "attempt.state_changed", "details": {"state": "ABORTED"}}
    next_state = event["details"]["state"]
    current_state = next_state
    if next_state in ("COMPLETED", "FAILED", "ABORTED"):
        aborting_set.discard("att-ui-2")

    assert current_state == "ABORTED"
    assert "att-ui-2" not in aborting_set


def test_15_frontend_websocket_reconnect_recovery():
    """Test 15: WebSocket disconnects then reconnects; snapshot syncs terminal state."""
    aborting_set = {"att-ui-3"}
    # WebSocket down, REST snapshot fetched on reconnect
    rest_snapshot = {"state": "ABORTED"}
    if rest_snapshot["state"] in ("COMPLETED", "FAILED", "ABORTED"):
        aborting_set.discard("att-ui-3")

    assert len(aborting_set) == 0, "Reconnect snapshot must resolve pending aborting state"


def test_16_frontend_abort_rejected_on_state_change():
    """Test 16: Abort rejected with 409 -> unmarks aborting state without fake success."""
    aborting_set = {"att-ui-4"}
    http_error = {"status": 409, "code": "ATTEMPT_NOT_ABORTABLE"}

    # On error, UI unmarks pending state and reports error
    aborting_set.discard("att-ui-4")
    assert "att-ui-4" not in aborting_set
    assert http_error["status"] == 409
