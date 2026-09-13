from __future__ import annotations

import threading
import time
from datetime import UTC, datetime

from pbl4.management_backend.gateways.mcp_port import RealMcpClientPort
from pbl4.management_protocol.messages import StartAttempt
from pbl4.runtime.management_endpoint import ManagementEndpoint


def test_real_mcp_bidirectional_correlation_and_reconnect() -> None:
    command_seen = threading.Event()
    result_seen = threading.Event()
    event_seen = threading.Event()
    received: list[tuple[str, dict]] = []

    def snapshot() -> dict[str, object]:
        return {
            "runtime_instance_id": "runtime-test",
            "active_job_id": None,
            "active_attempt_id": None,
            "attempt_state": None,
            "training_strategy": None,
            "checkpoint_policy": None,
            "epoch": None,
            "current_operation_id": None,
            "current_batch_ordinal": None,
            "model_version": None,
            "workers": [],
            "strategy_state": {},
            "checkpoint_state": None,
            "latest_checkpoint_id": None,
            "recovery_cursor": {},
            "dataset_build_id": None,
            "dataset_manifest_hash": None,
            "last_runtime_event_seq": 0,
            "management_event_gap_count": 0,
            "captured_at": datetime.now(UTC).isoformat(),
        }

    def command_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        assert kind == "START_ATTEMPT"
        command_seen.set()
        return {
            "command_id": payload["command_id"],
            "target_type": "ATTEMPT",
            "target_id": payload["attempt_id"],
            "status": "ACCEPTED",
            "result_code": "COMMAND_ACCEPTED",
            "message": "Accepted",
            "attempt_id": payload["attempt_id"],
        }

    endpoint = ManagementEndpoint(
        "127.0.0.1",
        0,
        runtime_instance_id="runtime-test",
        snapshot_provider=snapshot,
        command_handler=command_handler,
    )
    endpoint.start()
    try:
        host, port_number = endpoint.bound_address or ("", 0)
        client = RealMcpClientPort(host, port_number, timeout=2.0)

        def inbound(kind: str, payload: dict) -> None:
            received.append((kind, payload))
            if kind == "COMMAND_RESULT":
                result_seen.set()
            if kind == "RUNTIME_EVENT":
                event_seen.set()

        client.set_message_handler(inbound)
        client.set_dataset_resolver(
            lambda request: {
                "dataset_build_id": request["dataset_build_id"],
                "state": "READY",
                "manifest_uri": "/artifacts/v1/dataset-builds/build-1/manifest.json",
                "artifact_base_url": "http://dataset-manager:8001/artifacts/v1/dataset-builds/build-1",
                "dataset_manifest_hash": request["expected_dataset_manifest_hash"],
                "profile": "CNN_IMAGE_CLASSIFICATION_V1",
                "shard_count": 3,
                "batch_size": 32,
            }
        )
        assert client.connect()
        assert client.request_state()["runtime_instance_id"] == "runtime-test"

        start = StartAttempt.from_dict(
            {
                "command_id": "cmd-1",
                "job_id": "job-1",
                "attempt_id": "attempt-1",
                "execution_mode": "FRESH",
                "resolved_contract": {},
                "contract_hash": "contract-1",
                "resume_from_checkpoint_id": None,
                "requested_at": datetime.now(UTC).isoformat(),
            }
        ).to_dict()
        assert client.send_command("START_ATTEMPT", "cmd-1", "attempt-1", start)
        assert command_seen.wait(2.0)
        assert result_seen.wait(2.0)

        resolved = endpoint.resolve_dataset_build(
            {
                "job_id": "job-1",
                "attempt_id": "attempt-1",
                "dataset_build_id": "build-1",
                "expected_dataset_manifest_hash": "a" * 64,
            }
        )
        assert resolved["dataset_manifest_hash"] == "a" * 64
        assert "manifest" not in resolved

        assert endpoint.send_runtime_event(
            {
                "attempt_id": "attempt-1",
                "job_id": "job-1",
                "runtime_event_seq": 1,
                "event_type": "attempt.state_changed",
                "event_schema_version": 1,
                "occurred_at": datetime.now(UTC).isoformat(),
                "source_component": "runtime",
                "severity": "INFO",
                "details": {"state": "PROVISIONING"},
            }
        )
        assert event_seen.wait(2.0)
        assert any(kind == "RUNTIME_EVENT" and value["details"] for kind, value in received)

        client.disconnect()
        assert client.connect()
        assert client.request_state()["last_runtime_event_seq"] == 0
        client.disconnect()
    finally:
        endpoint.stop()


def test_mcp_congestion_send_timeout_disconnects() -> None:
    import socket

    from pbl4.management_protocol.codec import McpCodec
    from pbl4.management_protocol.messages import McpEnvelope
    from pbl4.transport.framed_socket import recv_exact, send_all

    def snapshot() -> dict[str, object]:
        return {
            "runtime_instance_id": "runtime-congestion-test",
            "active_job_id": None,
            "active_attempt_id": None,
            "attempt_state": None,
            "training_strategy": None,
            "checkpoint_policy": None,
            "epoch": None,
            "current_operation_id": None,
            "current_batch_ordinal": None,
            "model_version": None,
            "workers": [],
            "strategy_state": {},
            "checkpoint_state": None,
            "latest_checkpoint_id": None,
            "recovery_cursor": {},
            "dataset_build_id": None,
            "dataset_manifest_hash": None,
            "last_runtime_event_seq": 0,
            "management_event_gap_count": 0,
            "captured_at": datetime.now(UTC).isoformat(),
        }

    endpoint = ManagementEndpoint(
        "127.0.0.1",
        0,
        runtime_instance_id="runtime-congestion-test",
        snapshot_provider=snapshot,
        send_timeout=0.2,
    )
    endpoint.start()
    try:
        host, port_number = endpoint.bound_address or ("", 0)
        client_sock = socket.create_connection((host, port_number))
        client_sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        hello = McpEnvelope(
            message_type="MGMT_HELLO",
            message_id="hello-1",
            correlation_id=None,
            sent_at=datetime.now(UTC).isoformat(),
            runtime_instance_id="backend",
            payload={"backend_instance_id": "backend-1", "supported_protocol_versions": [1]},
        )
        McpCodec.write_message(client_sock, send_all, hello)
        ack = McpCodec.read_message(client_sock, recv_exact)
        assert ack.message_type == "MGMT_HELLO_ACK"
        deadline = time.monotonic() + 1.0
        while not endpoint.backend_connected and time.monotonic() < deadline:
            time.sleep(0.01)
        assert endpoint.backend_connected

        disconnected = False
        for i in range(10000):
            ok = endpoint.send_runtime_event(
                {
                    "attempt_id": "attempt-1",
                    "job_id": "job-1",
                    "runtime_event_seq": i + 1,
                    "event_type": "congestion.event",
                    "event_schema_version": 1,
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "source_component": "runtime",
                    "severity": "INFO",
                    "details": {"payload": "X" * 32768},
                }
            )
            if not ok:
                disconnected = True
                break

        assert disconnected, "send_runtime_event should fail when congestion timeout triggers"
        assert not endpoint.backend_connected, "ManagementEndpoint should mark backend disconnected"

        client_sock.close()

        new_client = RealMcpClientPort(host, port_number, timeout=2.0)
        assert new_client.connect()
        state = new_client.request_state()
        assert state["runtime_instance_id"] == "runtime-congestion-test"
        assert endpoint.backend_connected
        new_client.disconnect()
    finally:
        endpoint.stop()


def test_real_mcp_disconnect_reconnect_command_idempotency() -> None:
    handler_called = 0
    handler_started = threading.Event()
    allow_finish = threading.Event()

    def snapshot() -> dict[str, object]:
        return {
            "runtime_instance_id": "runtime-idemp-test",
            "active_job_id": None,
            "active_attempt_id": None,
            "attempt_state": None,
            "training_strategy": None,
            "checkpoint_policy": None,
            "epoch": None,
            "current_operation_id": None,
            "current_batch_ordinal": None,
            "model_version": None,
            "workers": [],
            "strategy_state": {},
            "checkpoint_state": None,
            "latest_checkpoint_id": None,
            "recovery_cursor": {},
            "dataset_build_id": None,
            "dataset_manifest_hash": None,
            "last_runtime_event_seq": 0,
            "management_event_gap_count": 0,
            "captured_at": datetime.now(UTC).isoformat(),
        }

    def slow_command_handler(kind: str, payload: dict[str, object]) -> dict[str, object]:
        nonlocal handler_called
        handler_called += 1
        handler_started.set()
        allow_finish.wait(timeout=5.0)
        return {
            "command_id": payload["command_id"],
            "target_type": "ATTEMPT",
            "target_id": payload["attempt_id"],
            "status": "ACCEPTED",
            "result_code": "COMMAND_ACCEPTED",
            "message": "Original execution completed",
            "attempt_id": payload["attempt_id"],
        }

    endpoint = ManagementEndpoint(
        "127.0.0.1",
        0,
        runtime_instance_id="runtime-idemp-test",
        snapshot_provider=snapshot,
        command_handler=slow_command_handler,
    )
    endpoint.start()
    try:
        host, port_number = endpoint.bound_address or ("", 0)

        # 1. Backend connects and sends command A
        client1 = RealMcpClientPort(host, port_number, timeout=2.0)
        assert client1.connect()

        start_payload = StartAttempt.from_dict(
            {
                "command_id": "cmd-real-reconnect",
                "job_id": "job-1",
                "attempt_id": "attempt-1",
                "execution_mode": "FRESH",
                "resolved_contract": {},
                "contract_hash": "contract-1",
                "resume_from_checkpoint_id": None,
                "requested_at": datetime.now(UTC).isoformat(),
            }
        ).to_dict()

        assert client1.send_command(
            "START_ATTEMPT", "cmd-real-reconnect", "attempt-1", start_payload
        )

        # 2. Runtime starts slow command handler
        assert handler_started.wait(timeout=2.0)
        assert handler_called == 1

        # 3. MCP socket disconnects while handler is running
        client1.disconnect()

        # 4. Backend reconnects
        client2 = RealMcpClientPort(host, port_number, timeout=2.0)
        assert client2.connect()

        results_received: list[dict] = []
        result_event = threading.Event()

        def inbound2(kind: str, payload: dict) -> None:
            if kind == "COMMAND_RESULT":
                results_received.append(payload)
                result_event.set()

        client2.set_message_handler(inbound2)

        # 5. Backend retries command A while original execution is still in-flight
        assert client2.send_command(
            "START_ATTEMPT", "cmd-real-reconnect", "attempt-1", start_payload
        )

        # 6. Allow original execution to complete
        allow_finish.set()

        # 7. Backend receives COMMAND_RESULT of original execution
        assert result_event.wait(timeout=3.0)
        assert len(results_received) == 1
        assert results_received[0]["command_id"] == "cmd-real-reconnect"
        assert results_received[0]["status"] == "ACCEPTED"
        assert results_received[0]["message"] == "Original execution completed"

        # 8. Handler was called exactly once!
        assert handler_called == 1

        # 9. Additional retry returns cached result without re-execution
        result_event.clear()
        results_received.clear()
        assert client2.send_command(
            "START_ATTEMPT", "cmd-real-reconnect", "attempt-1", start_payload
        )
        assert result_event.wait(timeout=2.0)
        assert len(results_received) == 1
        assert results_received[0]["message"] == "Original execution completed"
        assert handler_called == 1

        client2.disconnect()
    finally:
        allow_finish.set()
        endpoint.stop()
