from __future__ import annotations

import concurrent.futures
import threading
import time
from datetime import UTC, datetime

from pbl4.management_protocol.messages import McpEnvelope, StartAttempt
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
