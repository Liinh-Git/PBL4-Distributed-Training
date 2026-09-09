from __future__ import annotations

import threading
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
