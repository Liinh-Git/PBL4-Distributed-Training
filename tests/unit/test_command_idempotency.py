from __future__ import annotations

import concurrent.futures
import socket
import threading
import time
from datetime import UTC, datetime

import pytest

from pbl4.management_protocol.messages import CommandResult, McpEnvelope, StartAttempt
from pbl4.runtime.management_endpoint import ManagementEndpoint


def _make_start_attempt_payload(command_id: str, attempt_id: str = "attempt-1") -> dict:
    return StartAttempt.from_dict(
        {
            "command_id": command_id,
            "job_id": "job-1",
            "attempt_id": attempt_id,
            "execution_mode": "FRESH",
            "resolved_contract": {},
            "contract_hash": "hash-1",
            "resume_from_checkpoint_id": None,
            "requested_at": datetime.now(UTC).isoformat(),
        }
    ).to_dict()


def test_sequential_duplicate_command_executes_once_and_returns_cached_result() -> None:
    call_count = 0

    def command_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {
            "command_id": payload["command_id"],
            "target_type": "ATTEMPT",
            "target_id": payload["attempt_id"],
            "status": "ACCEPTED",
            "result_code": "COMMAND_ACCEPTED",
            "message": f"Execution count: {call_count}",
            "attempt_id": payload["attempt_id"],
        }

    endpoint = ManagementEndpoint("127.0.0.1", 0, command_handler=command_handler)
    responses: list[McpEnvelope] = []
    endpoint._write = lambda resp: responses.append(resp)

    payload = _make_start_attempt_payload("cmd-seq-1")

    # Send request 1
    req1 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-1",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    endpoint._serve_command(req1)

    assert call_count == 1
    assert len(responses) == 1
    assert responses[0].correlation_id == "msg-1"
    assert responses[0].payload.message == "Execution count: 1"

    # Send request 2 with duplicate command_id but new message_id
    req2 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-2",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    endpoint._serve_command(req2)

    # Handler must NOT have been called again!
    assert call_count == 1
    assert len(responses) == 2
    assert responses[1].correlation_id == "msg-2"
    # Result content must be cached and identical
    assert responses[1].payload.message == "Execution count: 1"
    assert responses[1].payload.command_id == "cmd-seq-1"
    assert responses[1].payload.status == "ACCEPTED"


def test_concurrent_duplicate_command_waits_and_executes_once() -> None:
    call_count = 0

    def slow_command_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)
        return {
            "command_id": payload["command_id"],
            "target_type": "ATTEMPT",
            "target_id": payload["attempt_id"],
            "status": "ACCEPTED",
            "result_code": "COMMAND_ACCEPTED",
            "message": "Slow executed",
            "attempt_id": payload["attempt_id"],
        }

    endpoint = ManagementEndpoint("127.0.0.1", 0, command_handler=slow_command_handler)
    responses_lock = threading.Lock()
    responses: list[McpEnvelope] = []

    def safe_write(resp: McpEnvelope) -> None:
        with responses_lock:
            responses.append(resp)

    endpoint._write = safe_write
    payload = _make_start_attempt_payload("cmd-concurrent-1")

    def run_worker(msg_id: str) -> None:
        req = McpEnvelope(
            message_type="START_ATTEMPT",
            message_id=msg_id,
            correlation_id=None,
            sent_at=datetime.now(UTC).isoformat(),
            runtime_instance_id="runtime-test",
            payload=payload,
        )
        endpoint._serve_command(req)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_worker, f"msg-c-{i}") for i in range(5)]
        concurrent.futures.wait(futures)

    assert call_count == 1
    assert len(responses) == 5
    for resp in responses:
        assert resp.payload.command_id == "cmd-concurrent-1"
        assert resp.payload.status == "ACCEPTED"
        assert resp.payload.message == "Slow executed"


def test_command_cache_bounded_eviction() -> None:
    endpoint = ManagementEndpoint("127.0.0.1", 0)
    endpoint._max_cached_commands = 10
    responses: list[McpEnvelope] = []
    endpoint._write = lambda resp: responses.append(resp)

    for i in range(25):
        payload = _make_start_attempt_payload(f"cmd-{i}", attempt_id=f"att-{i}")
        req = McpEnvelope(
            message_type="START_ATTEMPT",
            message_id=f"msg-{i}",
            correlation_id=None,
            sent_at=datetime.now(UTC).isoformat(),
            runtime_instance_id="runtime-test",
            payload=payload,
        )
        endpoint._serve_command(req)

    assert len(endpoint._command_results) == 10
    assert "cmd-0" not in endpoint._command_results
    assert "cmd-24" in endpoint._command_results


def test_command_handler_exception_returns_command_result_failed_and_caches() -> None:
    call_count = 0

    def failing_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("injected database error")

    endpoint = ManagementEndpoint("127.0.0.1", 0, command_handler=failing_handler)
    responses: list[McpEnvelope] = []
    endpoint._write = lambda resp: responses.append(resp)

    payload = _make_start_attempt_payload("cmd-fail-1")

    # Send first request
    req1 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-f-1",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    endpoint._serve_command(req1)

    assert call_count == 1
    assert len(responses) == 1
    # Must be COMMAND_RESULT, NOT MCP ERROR!
    assert responses[0].message_type == "COMMAND_RESULT"
    assert responses[0].correlation_id == "msg-f-1"
    assert responses[0].payload.command_id == "cmd-fail-1"
    assert responses[0].payload.status == "FAILED"
    assert responses[0].payload.result_code == "COMMAND_FAILED"
    assert "injected database error" in responses[0].payload.message

    # Send retry with same command_id but different message_id
    req2 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-f-2",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    endpoint._serve_command(req2)

    # Handler must NOT have executed a second time!
    assert call_count == 1
    assert len(responses) == 2
    assert responses[1].message_type == "COMMAND_RESULT"
    assert responses[1].correlation_id == "msg-f-2"
    assert responses[1].payload.command_id == "cmd-fail-1"
    assert responses[1].payload.status == "FAILED"
    assert responses[1].payload.result_code == "COMMAND_FAILED"
    assert "injected database error" in responses[1].payload.message


def test_command_handler_preserves_rejected_status() -> None:
    call_count = 0

    def rejecting_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {
            "command_id": payload["command_id"],
            "target_type": "ATTEMPT",
            "target_id": payload["attempt_id"],
            "status": "REJECTED",
            "result_code": "ACTIVE_ATTEMPT_EXISTS",
            "message": "Attempt is already active",
            "attempt_id": payload["attempt_id"],
        }

    endpoint = ManagementEndpoint("127.0.0.1", 0, command_handler=rejecting_handler)
    responses: list[McpEnvelope] = []
    endpoint._write = lambda resp: responses.append(resp)

    payload = _make_start_attempt_payload("cmd-rej-1")
    req1 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-r-1",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    endpoint._serve_command(req1)

    assert call_count == 1
    assert responses[0].message_type == "COMMAND_RESULT"
    assert responses[0].payload.status == "REJECTED"
    assert responses[0].payload.result_code == "ACTIVE_ATTEMPT_EXISTS"

    # Retry receives same cached REJECTED result
    req2 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-r-2",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    endpoint._serve_command(req2)
    assert call_count == 1
    assert responses[1].payload.status == "REJECTED"


def test_duplicate_command_attaches_to_inflight_execution_and_receives_canonical_result() -> None:
    call_count = 0
    allow_finish = threading.Event()
    handler_started = threading.Event()

    def slow_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        handler_started.set()
        allow_finish.wait(timeout=5.0)
        return {
            "command_id": payload["command_id"],
            "target_type": "ATTEMPT",
            "target_id": payload["attempt_id"],
            "status": "ACCEPTED",
            "result_code": "COMMAND_ACCEPTED",
            "message": "Finished slowly",
            "attempt_id": payload["attempt_id"],
        }

    # Short request_timeout (0.05s) to prove that duplicate request does NOT
    # time out or produce DEFERRED
    endpoint = ManagementEndpoint(
        "127.0.0.1", 0, command_handler=slow_handler, request_timeout=0.05
    )
    responses_lock = threading.Lock()
    responses: list[McpEnvelope] = []

    def safe_write(resp: McpEnvelope) -> None:
        with responses_lock:
            responses.append(resp)

    endpoint._write = safe_write
    payload = _make_start_attempt_payload("cmd-timeout-1")

    # 1. Start leader thread for command A
    req1 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-t-1",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    t1 = threading.Thread(target=endpoint._serve_command, args=(req1,), daemon=True)
    t1.start()

    assert handler_started.wait(timeout=2.0)
    assert call_count == 1

    # 2. Duplicate request A is sent while original execution is still in-flight
    req2 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-t-2",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    t2 = threading.Thread(target=endpoint._serve_command, args=(req2,), daemon=True)
    t2.start()

    # Wait longer than request_timeout (0.1s > 0.05s)
    time.sleep(0.1)

    # 3. Invariant: NO fake COMMAND_RESULT DEFERRED due to local timeout!
    with responses_lock:
        assert len(responses) == 0

    # 4. Invariant: Handler call_count is still 1 (no second execution)!
    assert call_count == 1

    # 5. Allow original execution to complete
    allow_finish.set()
    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    # Both requests receive the canonical result of command A
    with responses_lock:
        assert len(responses) == 2
        resp1 = next(r for r in responses if r.correlation_id == "msg-t-1")
        resp2 = next(r for r in responses if r.correlation_id == "msg-t-2")

    assert resp1.payload.status == "ACCEPTED"
    assert resp1.payload.result_code == "COMMAND_ACCEPTED"
    assert resp1.payload.message == "Finished slowly"

    assert resp2.payload.status == "ACCEPTED"
    assert resp2.payload.result_code == "COMMAND_ACCEPTED"
    assert resp2.payload.message == "Finished slowly"

    # 6. Result is cached in endpoint
    with endpoint._command_lock:
        assert "cmd-timeout-1" in endpoint._command_results
        assert "cmd-timeout-1" not in endpoint._in_flight_commands

    # 7. Subsequent retry of A returns cached result without re-execution
    req3 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-t-3",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    endpoint._serve_command(req3)
    with responses_lock:
        assert len(responses) == 3
        resp3 = next(r for r in responses if r.correlation_id == "msg-t-3")
    assert resp3.payload.status == "ACCEPTED"
    assert resp3.payload.message == "Finished slowly"

    # 8. Handler call_count is STILL 1!
    assert call_count == 1


def test_disconnect_does_not_clear_in_flight_command_or_reexecute() -> None:
    call_count = 0
    allow_finish = threading.Event()
    handler_started = threading.Event()

    def slow_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        handler_started.set()
        allow_finish.wait(timeout=5.0)
        return {
            "command_id": payload["command_id"],
            "target_type": "ATTEMPT",
            "target_id": payload["attempt_id"],
            "status": "ACCEPTED",
            "result_code": "COMMAND_ACCEPTED",
            "message": "Execution across disconnect",
            "attempt_id": payload["attempt_id"],
        }

    endpoint = ManagementEndpoint("127.0.0.1", 0, command_handler=slow_handler, request_timeout=2.0)
    responses_lock = threading.Lock()
    responses: list[McpEnvelope] = []

    def safe_write(resp: McpEnvelope) -> None:
        with responses_lock:
            responses.append(resp)

    endpoint._write = safe_write
    payload = _make_start_attempt_payload("cmd-disconn-1")

    # Start command 1
    req1 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-d-1",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    t1 = threading.Thread(target=endpoint._serve_command, args=(req1,), daemon=True)
    t1.start()

    assert handler_started.wait(timeout=2.0)
    assert call_count == 1

    # Simulate transport disconnect
    endpoint._disconnect_socket(reason="Backend disconnected")

    # CRITICAL: in-flight command must NOT be cleared by disconnect!
    with endpoint._command_lock:
        assert "cmd-disconn-1" in endpoint._in_flight_commands

    # Reconnect retry arrives while handler is still active
    retry_completed = threading.Event()
    req2 = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-d-2",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )

    def run_retry() -> None:
        endpoint._serve_command(req2)
        retry_completed.set()

    t2 = threading.Thread(target=run_retry, daemon=True)
    t2.start()

    # Allow original execution to complete
    time.sleep(0.05)
    allow_finish.set()

    t1.join(timeout=2.0)
    t2.join(timeout=2.0)

    # Handler was called only once!
    assert call_count == 1
    assert retry_completed.is_set()

    # Retry received the result from original execution
    with responses_lock:
        retry_resp = next(r for r in responses if r.correlation_id == "msg-d-2")
    assert retry_resp.payload.status == "ACCEPTED"
    assert retry_resp.payload.message == "Execution across disconnect"


def test_command_handler_returning_canonical_command_result_preserves_status() -> None:
    call_count = 0

    def deferred_handler(kind: str, payload: dict[str, object]) -> CommandResult:
        nonlocal call_count
        call_count += 1
        return CommandResult.from_dict(
            {
                "command_id": str(payload["command_id"]),
                "target_type": "ATTEMPT",
                "target_id": str(payload["attempt_id"]),
                "status": "DEFERRED",
                "result_code": "SAFE_POINT_PENDING",
                "message": "Waiting for safe point barrier",
                "attempt_id": str(payload["attempt_id"]),
            }
        )

    endpoint = ManagementEndpoint("127.0.0.1", 0, command_handler=deferred_handler)
    responses: list[McpEnvelope] = []
    endpoint._write = lambda resp: responses.append(resp)

    payload = _make_start_attempt_payload("cmd-deferred-1")
    req = McpEnvelope(
        message_type="START_ATTEMPT",
        message_id="msg-def-1",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload=payload,
    )
    endpoint._serve_command(req)

    assert call_count == 1
    assert len(responses) == 1
    resp = responses[0]
    assert resp.message_type == "COMMAND_RESULT"
    assert resp.payload.command_id == "cmd-deferred-1"
    assert resp.payload.status == "DEFERRED"
    assert resp.payload.result_code == "SAFE_POINT_PENDING"


def test_defensive_validation_serve_command_rejects_non_command_message() -> None:
    endpoint = ManagementEndpoint("127.0.0.1", 0)
    responses: list[McpEnvelope] = []
    endpoint._write = lambda resp: responses.append(resp)

    req = McpEnvelope(
        message_type="RESOLVE_DATASET_BUILD",
        message_id="msg-err-1",
        correlation_id=None,
        sent_at=datetime.now(UTC).isoformat(),
        runtime_instance_id="runtime-test",
        payload={
            "job_id": "job-1",
            "attempt_id": "attempt-1",
            "dataset_build_id": "build-1",
            "expected_dataset_manifest_hash": "hash-1",
        },
    )
    endpoint._serve_command(req)

    assert len(responses) == 1
    resp = responses[0]
    assert resp.message_type == "ERROR"
    assert resp.correlation_id == "msg-err-1"
    assert resp.payload.code == "INVALID_COMMAND_ID"


def test_response_socket_race_does_not_leak_to_new_connection() -> None:
    allow_finish = threading.Event()
    handler_started = threading.Event()

    def slow_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        handler_started.set()
        allow_finish.wait(timeout=5.0)
        return {
            "command_id": payload["command_id"],
            "target_type": "ATTEMPT",
            "target_id": payload["attempt_id"],
            "status": "ACCEPTED",
            "result_code": "COMMAND_ACCEPTED",
            "message": "Done",
            "attempt_id": payload["attempt_id"],
        }

    endpoint = ManagementEndpoint("127.0.0.1", 0, command_handler=slow_handler)

    # Create two pairs of connected sockets: Pair A and Pair B
    sock_a_client, sock_a_server = socket.socketpair()
    sock_b_client, sock_b_server = socket.socketpair()
    try:
        # Endpoint initially has active connection on sock_a_server
        with endpoint._connection_lock:
            endpoint._sock = sock_a_server
            endpoint._backend_connected.set()

        payload = _make_start_attempt_payload("cmd-race-1")
        req_a = McpEnvelope(
            message_type="START_ATTEMPT",
            message_id="msg-race-a",
            correlation_id=None,
            sent_at=datetime.now(UTC).isoformat(),
            runtime_instance_id="runtime-test",
            payload=payload,
        )

        # Start serve_command on socket A
        t = threading.Thread(
            target=endpoint._serve_command,
            args=(req_a, sock_a_server),
            daemon=True,
        )
        t.start()

        assert handler_started.wait(timeout=2.0)

        # BEFORE response write, Backend reconnects: endpoint._sock switches to sock_b_server
        with endpoint._connection_lock:
            endpoint._sock = sock_b_server

        # Now allow handler to finish and write response
        allow_finish.set()
        t.join(timeout=2.0)

        # Invariant: Socket B must NEVER receive the response destined for Socket A!
        sock_b_client.setblocking(False)
        with pytest.raises(BlockingIOError):
            sock_b_client.recv(4096)
    finally:
        sock_a_client.close()
        sock_a_server.close()
        sock_b_client.close()
        sock_b_server.close()
