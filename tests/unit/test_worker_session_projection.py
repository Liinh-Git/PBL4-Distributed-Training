"""Unit tests for Worker Session projection, terminal worker preservation, and session_id consistency."""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from pbl4.common.worker_admission import issue_worker_join_token
from pbl4.management_backend.schemas.attempt import WorkerSessionItem
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    MESSAGE_TYPE_ERROR,
    UNASSIGNED_WORKER_ID,
)
from pbl4.protocol.messages import (
    Error,
    Hello,
    HelloAck,
    build_control_frame,
    decode_control_message,
)
from pbl4.protocol.parameter_manifest import ParameterEntry, ParameterManifest
from pbl4.runtime.parameter_server import ParameterServer
from pbl4.runtime.process import _AttemptRunner
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.transport.framed_socket import recv_exact


def dummy_manifest() -> ParameterManifest:
    return ParameterManifest.create([ParameterEntry(0, "weight", (3,), "float32", 3, 0, 12)])


def _make_hello(attempt_id: str, node_id: str, alloc_id: str, secret: str) -> Hello:
    token = issue_worker_join_token(secret, attempt_id, alloc_id, node_id, ttl_seconds=600)
    return Hello.from_dict(
        {
            "node_label": "worker-node-0",
            "client_instance_id": "client-instance-1",
            "role": "worker",
            "protocol_version": 1,
            "framework_adapter": "pytorch",
            "supported_tensor_encoding": ["fp32_le_v1"],
            "supported_strategy_capabilities": ["strict_bsp"],
            "attempt_id": attempt_id,
            "allocation_id": alloc_id,
            "node_id": node_id,
            "worker_join_token": token,
        }
    )


def _safe_serve(server: ParameterServer, sock: socket.socket, addr: tuple[str, int]) -> None:
    with contextlib.suppress(Exception):
        server._serve_connection(sock, addr)


def test_worker_disconnect_retains_session_in_snapshot() -> None:
    """Worker disconnect must retain worker in worker_snapshots with state=DISCONNECTED and same session_id."""
    attempt_id = "attempt-disconnect-test"
    secret = "adm-secret-12345"
    registry = WorkerRegistry(attempt_id, 1)
    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id=attempt_id,
        job_id="job-1",
        expected_workers=1,
        manifest=dummy_manifest(),
        registry=registry,
        worker_admission_secret=secret,
        require_worker_admission=True,
    )

    s_sock, c_sock = socket.socketpair()
    thread = threading.Thread(
        target=_safe_serve,
        args=(server, s_sock, ("127.0.0.1", 12345)),
        daemon=True,
    )
    thread.start()

    try:
        # 1. Send HELLO
        hello = _make_hello(attempt_id, "node-1", "alloc-1", secret)
        frame = build_control_frame(hello, session_id=0, worker_id=UNASSIGNED_WORKER_ID)
        frame.write_to(c_sock, lambda s, b: s.sendall(b))

        # 2. Read HELLO_ACK
        reply_frame = DTPFrame.read_from(c_sock, recv_exact)
        reply = decode_control_message(reply_frame.header.message_type, reply_frame.payload)
        assert isinstance(reply, HelloAck)
        session_id = int(reply.session_id)

        # Active snapshots
        active_snaps = server.worker_snapshots()
        assert len(active_snaps) == 1
        assert active_snaps[0]["worker_id"] == 0
        assert active_snaps[0]["session_id"] == session_id
        assert active_snaps[0]["state"] == SessionState.PROVISIONING.value
        assert active_snaps[0]["disconnected_at"] is None
        assert active_snaps[0]["node_id"] == "node-1"
        assert active_snaps[0]["allocation_id"] == "alloc-1"

        # 3. Simulate Worker disconnect (close client socket abruptly)
        c_sock.close()
        thread.join(timeout=2.0)

        # 4. Check post-disconnect snapshots
        # Transport connection is popped
        assert len(server.worker_ids()) == 0

        # Authoritative snapshots still contain the worker!
        final_snaps = server.worker_snapshots()
        assert len(final_snaps) == 1
        worker = final_snaps[0]
        assert worker["worker_id"] == 0
        assert worker["session_id"] == session_id
        assert worker["state"] == SessionState.DISCONNECTED.value
        assert worker["disconnected_at"] is not None
        assert isinstance(worker["disconnected_at"], str)
        assert worker["failure_code"] is None
        assert worker["node_id"] == "node-1"
        assert worker["allocation_id"] == "alloc-1"
    finally:
        s_sock.close()


def test_worker_fatal_error_retains_failed_state_and_failure_code() -> None:
    """Worker fatal error must retain worker in worker_snapshots with state=FAILED and failure_code."""
    attempt_id = "attempt-fatal-err-test"
    secret = "adm-secret-12345"
    registry = WorkerRegistry(attempt_id, 1)
    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id=attempt_id,
        job_id="job-1",
        expected_workers=1,
        manifest=dummy_manifest(),
        registry=registry,
        worker_admission_secret=secret,
        require_worker_admission=True,
    )

    s_sock, c_sock = socket.socketpair()
    thread = threading.Thread(
        target=_safe_serve,
        args=(server, s_sock, ("127.0.0.1", 12345)),
        daemon=True,
    )
    thread.start()

    try:
        hello = _make_hello(attempt_id, "node-2", "alloc-2", secret)
        frame = build_control_frame(hello, session_id=0, worker_id=UNASSIGNED_WORKER_ID)
        frame.write_to(c_sock, lambda s, b: s.sendall(b))

        reply_frame = DTPFrame.read_from(c_sock, recv_exact)
        reply = decode_control_message(reply_frame.header.message_type, reply_frame.payload)
        assert isinstance(reply, HelloAck)
        session_id = int(reply.session_id)

        # Send fatal ERROR frame
        err_msg = Error.from_dict(
            {
                "error_code": "WORKER_OUT_OF_MEMORY",
                "scope": "SESSION",
                "severity": "CRITICAL",
                "message": "CUDA OOM encountered during backward pass",
                "retryable": False,
            }
        )
        err_frame = build_control_frame(err_msg, session_id=session_id, worker_id=0)
        err_frame.write_to(c_sock, lambda s, b: s.sendall(b))

        thread.join(timeout=2.0)

        final_snaps = server.worker_snapshots()
        assert len(final_snaps) == 1
        worker = final_snaps[0]
        assert worker["worker_id"] == 0
        assert worker["session_id"] == session_id
        assert worker["state"] == SessionState.FAILED.value
        assert worker["failure_code"] == "WORKER_OUT_OF_MEMORY"
        assert worker["disconnected_at"] is not None
        assert worker["node_id"] == "node-2"
        assert worker["allocation_id"] == "alloc-2"
    finally:
        c_sock.close()
        s_sock.close()


def test_server_stop_preserves_terminal_worker_snapshots() -> None:
    """After server.stop(), worker_snapshots() still returns all workers in terminal state."""
    attempt_id = "attempt-stop-preserves-test"
    secret = "adm-secret-12345"
    registry = WorkerRegistry(attempt_id, 1)
    server = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id=attempt_id,
        job_id="job-1",
        expected_workers=1,
        manifest=dummy_manifest(),
        registry=registry,
        worker_admission_secret=secret,
        require_worker_admission=True,
    )

    s_sock, c_sock = socket.socketpair()
    thread = threading.Thread(
        target=_safe_serve,
        args=(server, s_sock, ("127.0.0.1", 12345)),
        daemon=True,
    )
    thread.start()

    try:
        hello = _make_hello(attempt_id, "node-stop", "alloc-stop", secret)
        frame = build_control_frame(hello, session_id=0, worker_id=UNASSIGNED_WORKER_ID)
        frame.write_to(c_sock, lambda s, b: s.sendall(b))

        reply_frame = DTPFrame.read_from(c_sock, recv_exact)
        reply = decode_control_message(reply_frame.header.message_type, reply_frame.payload)
        assert isinstance(reply, HelloAck)
        session_id = int(reply.session_id)

        # Call server.stop()
        server.stop()
        c_sock.close()
        thread.join(timeout=2.0)

        # Verify worker_snapshots() returns the terminal worker
        final_snaps = server.worker_snapshots()
        assert len(final_snaps) == 1
        worker = final_snaps[0]
        assert worker["worker_id"] == 0
        assert worker["session_id"] == session_id
        assert worker["state"] == SessionState.DISCONNECTED.value
        assert worker["disconnected_at"] is not None
        assert worker["node_id"] == "node-stop"
        assert worker["allocation_id"] == "alloc-stop"
    finally:
        s_sock.close()


def test_runtime_process_snapshot_terminal_workers() -> None:
    """RuntimeProcess snapshot includes disconnected_at and failure_code for terminal workers."""
    mock_proc = MagicMock()
    mock_mgmt = MagicMock()
    runner = _AttemptRunner(
        process=mock_proc,
        payload={
            "job_id": "job-snap-1",
            "attempt_id": "atm-snap-1",
            "resolved_contract": {
                "synchronization": {"training_strategy": "strict_bsp"},
                "checkpoint_policy": {"type": "every_step"},
                "dataset": {"dataset_build_id": "bld-1", "dataset_manifest_hash": "a" * 64},
            },
        },
        management=mock_mgmt,
    )
    runner._state = "FAILED"
    runner._final_workers = (
        {
            "worker_id": 0,
            "session_id": 555666,
            "node_label": "worker-terminal",
            "state": "FAILED",
            "protocol_version": 1,
            "connected_at": "2026-09-28T14:00:00+00:00",
            "last_heartbeat_at": "2026-09-28T14:05:00+00:00",
            "disconnected_at": "2026-09-28T14:05:10+00:00",
            "failure_code": "NODE_FAILED",
            "shard_id": 0,
            "local_model_version": 1,
            "node_id": "node-fail-1",
            "allocation_id": "alloc-fail-1",
        },
    )

    snap = runner.snapshot("instance-test-1")
    assert snap["active_attempt_id"] == "atm-snap-1"
    assert snap["attempt_state"] == "FAILED"
    assert len(snap["workers"]) == 1
    w = snap["workers"][0]
    assert w["worker_id"] == 0
    assert w["session_id"] == "555666"
    assert w["state"] == "FAILED"
    assert w["disconnected_at"] == "2026-09-28T14:05:10+00:00"
    assert w["failure_code"] == "NODE_FAILED"
    assert w["node_id"] == "node-fail-1"
    assert w["allocation_id"] == "alloc-fail-1"


def test_worker_session_repository_update_snapshot_projection_direct() -> None:
    """worker_session_repository.update_snapshot_projection updates disconnected_at and failure_code."""
    from pbl4.management_backend.repositories import worker_session_repository

    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = {
        "session_id": 1234,
        "attempt_id": "atm-rep-1",
        "worker_id": 0,
        "node_label": "node-lbl",
        "state": "DISCONNECTED",
        "last_heartbeat_at": None,
        "disconnected_at": datetime(2026, 9, 28, 14, 30, tzinfo=UTC),
        "failure_code": "CLIENT_DISCONNECT",
        "node_id": "node-1",
        "allocation_id": "alloc-1",
    }

    res = worker_session_repository.update_snapshot_projection(
        mock_conn,
        session_id=1234,
        attempt_id="atm-rep-1",
        worker_id=0,
        node_label="node-lbl",
        state="DISCONNECTED",
        last_heartbeat_at=None,
        disconnected_at=datetime(2026, 9, 28, 14, 30, tzinfo=UTC),
        failure_code="CLIENT_DISCONNECT",
        node_id="node-1",
        allocation_id="alloc-1",
    )

    assert res is not None
    assert res["state"] == "DISCONNECTED"
    assert res["failure_code"] == "CLIENT_DISCONNECT"
    # Verify execute query and parameters
    mock_cur.execute.assert_called_once()
    query, params = mock_cur.execute.call_args[0]
    assert "disconnected_at = COALESCE(%s, disconnected_at)" in query
    assert "failure_code = COALESCE(%s, failure_code)" in query
    assert params[3] == datetime(2026, 9, 28, 14, 30, tzinfo=UTC)
    assert params[4] == "CLIENT_DISCONNECT"


def test_worker_session_item_contract() -> None:
    """WorkerSessionItem requires protocol_version, connected_at, and accepts disconnected_at/failure_code."""
    now = datetime.now(UTC)
    disc = datetime.now(UTC)
    item = WorkerSessionItem(
        worker_id=0,
        session_id="777",
        node_label="worker-0",
        state="DISCONNECTED",
        protocol_version=1,
        connected_at=now,
        last_heartbeat_at=now,
        disconnected_at=disc,
        failure_code="TEST_FAIL",
        node_id="n-1",
        allocation_id="a-1",
    )
    assert item.session_id == "777"
    assert item.state == "DISCONNECTED"
    assert item.disconnected_at == disc
    assert item.failure_code == "TEST_FAIL"


def test_runtime_gateway_persists_disconnected_and_failure_code() -> None:
    """RuntimeGateway must persist session_id, state=DISCONNECTED, disconnected_at and failure_code."""
    from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway

    port = MagicMock()
    port.request_state.return_value = None
    gw = RuntimeGateway(port=port)

    disconnected_time_str = "2026-09-28T14:15:00+00:00"
    snapshot_payload = {
        "runtime_instance_id": "rt-inst-1",
        "active_job_id": "job-gw-1",
        "active_attempt_id": "atm-gw-1",
        "attempt_state": "FAILED",
        "training_strategy": "strict_bsp",
        "checkpoint_policy": "every_step",
        "epoch": 2,
        "current_operation_id": 4,
        "current_batch_ordinal": 2,
        "model_version": 4,
        "workers": [
            {
                "worker_id": 0,
                "session_id": "999888",
                "node_label": "worker-node-target",
                "state": "FAILED",
                "protocol_version": 1,
                "connected_at": "2026-09-28T14:00:00+00:00",
                "last_heartbeat_at": "2026-09-28T14:14:55+00:00",
                "disconnected_at": disconnected_time_str,
                "failure_code": "WORKER_HARDWARE_FAILURE",
                "shard_id": 0,
                "local_model_version": 4,
                "node_id": "node-target-1",
                "allocation_id": "alloc-target-1",
            }
        ],
        "strategy_state": {},
        "checkpoint_state": "IDLE",
        "latest_checkpoint_id": None,
        "recovery_cursor": {},
        "dataset_build_id": "bld-1",
        "dataset_manifest_hash": "hash-1",
        "last_runtime_event_seq": 15,
        "management_event_gap_count": 0,
        "captured_at": "2026-09-28T14:15:01+00:00",
    }

    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_db.transaction.return_value.__enter__.return_value = mock_conn

    # 1. Existing session in DB -> update_snapshot_projection returns non-None
    with (
        patch("pbl4.management_backend.db.transaction", return_value=mock_db.transaction()),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt"
        ) as mock_get_attempt,
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state"),
        patch(
            "pbl4.management_backend.repositories.worker_session_repository.update_snapshot_projection"
        ) as mock_update_proj,
        patch(
            "pbl4.management_backend.repositories.worker_session_repository.upsert_session"
        ) as mock_upsert,
    ):
        mock_get_attempt.return_value = {
            "attempt_id": "atm-gw-1",
            "state": "RUNNING",
            "runtime_metadata": {},
        }
        mock_update_proj.return_value = {"session_id": 999888}

        gw.handle_state_snapshot(snapshot_payload)

        mock_update_proj.assert_called_once()
        kwargs = mock_update_proj.call_args[1]
        assert kwargs["session_id"] == 999888
        assert kwargs["attempt_id"] == "atm-gw-1"
        assert kwargs["worker_id"] == 0
        assert kwargs["state"] == "FAILED"
        assert kwargs["disconnected_at"] == datetime.fromisoformat(disconnected_time_str)
        assert kwargs["failure_code"] == "WORKER_HARDWARE_FAILURE"
        assert kwargs["node_id"] == "node-target-1"
        assert kwargs["allocation_id"] == "alloc-target-1"
        mock_upsert.assert_not_called()

    # 2. Non-existing session in DB -> update_snapshot_projection returns None -> fallback to upsert_session
    with (
        patch("pbl4.management_backend.db.transaction", return_value=mock_db.transaction()),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt"
        ) as mock_get_attempt,
        patch("pbl4.management_backend.repositories.attempt_repository.update_attempt_state"),
        patch(
            "pbl4.management_backend.repositories.worker_session_repository.update_snapshot_projection",
            return_value=None,
        ),
        patch(
            "pbl4.management_backend.repositories.worker_session_repository.upsert_session"
        ) as mock_upsert,
    ):
        mock_get_attempt.return_value = {
            "attempt_id": "atm-gw-1",
            "state": "RUNNING",
            "runtime_metadata": {},
        }

        gw.handle_state_snapshot(snapshot_payload)

        mock_upsert.assert_called_once()
        kwargs = mock_upsert.call_args[1]
        assert kwargs["session_id"] == 999888
        assert kwargs["attempt_id"] == "atm-gw-1"
        assert kwargs["worker_id"] == 0
        assert kwargs["state"] == "FAILED"
        assert kwargs["disconnected_at"] == datetime.fromisoformat(disconnected_time_str)
        assert kwargs["failure_code"] == "WORKER_HARDWARE_FAILURE"
        assert kwargs["node_id"] == "node-target-1"
        assert kwargs["allocation_id"] == "alloc-target-1"
