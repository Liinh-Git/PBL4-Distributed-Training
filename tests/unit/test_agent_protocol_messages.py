"""Unit tests for agent protocol wire schemas, payloads, and envelope validation.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1
"""

from __future__ import annotations

import json
import unittest

from pbl4.agent_protocol.messages import (
    COMMAND_STATUS_ACCEPTED,
    COMMAND_STATUS_REJECTED,
    COMMAND_TYPE_START_WORKER,
    COMMAND_TYPE_STOP_WORKER,
    MESSAGE_TYPE_AGENT_HELLO,
    MESSAGE_TYPE_COMMAND,
    MESSAGE_TYPE_COMMAND_ACK,
    MESSAGE_TYPE_HEARTBEAT,
    MESSAGE_TYPE_HELLO_ACK,
    MESSAGE_TYPE_RESOURCE_SNAPSHOT,
    MESSAGE_TYPE_WORKER_STATUS,
    WORKER_ACTUAL_STATE_ENDED,
    WORKER_ACTUAL_STATE_FAILED,
    WORKER_ACTUAL_STATE_STARTED,
    ActiveAllocationItem,
    AgentEnvelope,
    AgentHelloPayload,
    AgentMessageError,
    CommandAckPayload,
    GpuSnapshotItem,
    HeartbeatPayload,
    HelloAckPayload,
    ResourceSnapshotPayload,
    StartWorkerPayload,
    StopWorkerPayload,
    WorkerStatusPayload,
    parse_agent_envelope,
)


class TestAgentProtocolMessages(unittest.TestCase):
    def setUp(self) -> None:
        self.node_id = "node-worker-01"

    def test_agent_hello_roundtrip(self) -> None:
        alloc = ActiveAllocationItem(
            allocation_id="alloc-100",
            attempt_id="attempt-01",
            local_state="RUNNING",
            pid=12345,
        )
        payload = AgentHelloPayload(
            agent_version="0.1.0",
            platform="Linux-6.5.0-x86_64",
            active_allocations=(alloc,),
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_AGENT_HELLO,
            node_id=self.node_id,
            payload=payload,
            correlation_id="corr-1",
        )
        wire_json = env.to_json()
        parsed = parse_agent_envelope(wire_json)

        self.assertEqual(parsed.message_type, MESSAGE_TYPE_AGENT_HELLO)
        self.assertEqual(parsed.node_id, self.node_id)
        self.assertEqual(parsed.correlation_id, "corr-1")
        self.assertIsInstance(parsed.payload, AgentHelloPayload)
        self.assertEqual(parsed.payload.agent_version, "0.1.0")
        self.assertEqual(len(parsed.payload.active_allocations), 1)
        self.assertEqual(parsed.payload.active_allocations[0].allocation_id, "alloc-100")
        self.assertEqual(parsed.payload.active_allocations[0].local_state, "RUNNING")
        self.assertEqual(parsed.payload.active_allocations[0].pid, 12345)

    def test_hello_ack_roundtrip(self) -> None:
        payload = HelloAckPayload(
            heartbeat_interval_seconds=5.0,
            telemetry_interval_seconds=10.0,
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_HELLO_ACK,
            node_id=self.node_id,
            payload=payload,
        )
        wire_json = env.to_json()
        parsed = parse_agent_envelope(wire_json)

        self.assertEqual(parsed.message_type, MESSAGE_TYPE_HELLO_ACK)
        self.assertIsInstance(parsed.payload, HelloAckPayload)
        self.assertEqual(parsed.payload.heartbeat_interval_seconds, 5.0)
        self.assertEqual(parsed.payload.telemetry_interval_seconds, 10.0)

    def test_heartbeat_roundtrip(self) -> None:
        payload = HeartbeatPayload(active_allocations_count=2)
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_HEARTBEAT,
            node_id=self.node_id,
            payload=payload,
        )
        wire_json = env.to_json()
        parsed = parse_agent_envelope(wire_json)

        self.assertEqual(parsed.message_type, MESSAGE_TYPE_HEARTBEAT)
        self.assertIsInstance(parsed.payload, HeartbeatPayload)
        self.assertEqual(parsed.payload.active_allocations_count, 2)

    def test_resource_snapshot_roundtrip(self) -> None:
        gpu = GpuSnapshotItem(
            index=0,
            gpu_utilization_pct=42.5,
            vram_used_bytes=2_000_000_000,
            vram_total_bytes=8_000_000_000,
        )
        payload = ResourceSnapshotPayload(
            cpu_utilization_pct=15.2,
            ram_used_bytes=4_000_000_000,
            ram_total_bytes=16_000_000_000,
            gpus=(gpu,),
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_RESOURCE_SNAPSHOT,
            node_id=self.node_id,
            payload=payload,
        )
        wire_json = env.to_json()
        parsed = parse_agent_envelope(wire_json)

        self.assertEqual(parsed.message_type, MESSAGE_TYPE_RESOURCE_SNAPSHOT)
        self.assertIsInstance(parsed.payload, ResourceSnapshotPayload)
        self.assertEqual(parsed.payload.cpu_utilization_pct, 15.2)
        self.assertEqual(len(parsed.payload.gpus), 1)
        self.assertEqual(parsed.payload.gpus[0].index, 0)
        self.assertEqual(parsed.payload.gpus[0].gpu_utilization_pct, 42.5)

    def test_command_start_worker_roundtrip(self) -> None:
        token = "eyJhbGciOiJIUzI1NiJ9.signature123"
        payload = StartWorkerPayload(
            command_id="cmd-start-1",
            allocation_id="alloc-1",
            attempt_id="attempt-1",
            runtime_host="192.168.1.50",
            runtime_port=9000,
            device="cuda:0",
            initialization_seed=42,
            worker_join_token=token,
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            node_id=self.node_id,
            payload=payload,
        )
        wire_json = env.to_json()
        parsed = parse_agent_envelope(wire_json)

        self.assertEqual(parsed.message_type, MESSAGE_TYPE_COMMAND)
        self.assertIsInstance(parsed.payload, StartWorkerPayload)
        self.assertEqual(parsed.payload.command_type, COMMAND_TYPE_START_WORKER)
        self.assertEqual(parsed.payload.runtime_host, "192.168.1.50")
        self.assertEqual(parsed.payload.runtime_port, 9000)
        self.assertEqual(parsed.payload.device, "cuda:0")
        self.assertEqual(parsed.payload.initialization_seed, 42)
        self.assertEqual(parsed.payload.worker_join_token, token)

    def test_command_stop_worker_roundtrip(self) -> None:
        payload = StopWorkerPayload(
            command_id="cmd-stop-1",
            allocation_id="alloc-1",
            grace_period_seconds=15.0,
            force=True,
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            node_id=self.node_id,
            payload=payload,
        )
        wire_json = env.to_json()
        parsed = parse_agent_envelope(wire_json)

        self.assertEqual(parsed.message_type, MESSAGE_TYPE_COMMAND)
        self.assertIsInstance(parsed.payload, StopWorkerPayload)
        self.assertEqual(parsed.payload.command_type, COMMAND_TYPE_STOP_WORKER)
        self.assertEqual(parsed.payload.grace_period_seconds, 15.0)
        self.assertTrue(parsed.payload.force)

    def test_command_ack_roundtrip(self) -> None:
        for status in [COMMAND_STATUS_ACCEPTED, COMMAND_STATUS_REJECTED]:
            payload = CommandAckPayload(
                command_id="cmd-1",
                allocation_id="alloc-1",
                status=status,
                error_code="ALLOCATION_ALREADY_ACTIVE" if status == COMMAND_STATUS_REJECTED else None,
                error_message="Already running" if status == COMMAND_STATUS_REJECTED else None,
            )
            env = AgentEnvelope(
                message_type=MESSAGE_TYPE_COMMAND_ACK,
                node_id=self.node_id,
                payload=payload,
            )
            parsed = parse_agent_envelope(env.to_json())
            self.assertEqual(parsed.message_type, MESSAGE_TYPE_COMMAND_ACK)
            self.assertIsInstance(parsed.payload, CommandAckPayload)
            self.assertEqual(parsed.payload.status, status)

    def test_worker_status_roundtrip(self) -> None:
        for state in [WORKER_ACTUAL_STATE_STARTED, WORKER_ACTUAL_STATE_ENDED, WORKER_ACTUAL_STATE_FAILED]:
            payload = WorkerStatusPayload(
                allocation_id="alloc-1",
                attempt_id="attempt-1",
                actual_state=state,
                exit_code=1 if state == WORKER_ACTUAL_STATE_FAILED else 0,
                failure_code="SPAWN_FAILED" if state == WORKER_ACTUAL_STATE_FAILED else None,
                failure_message="Failed to start" if state == WORKER_ACTUAL_STATE_FAILED else None,
            )
            env = AgentEnvelope(
                message_type=MESSAGE_TYPE_WORKER_STATUS,
                node_id=self.node_id,
                payload=payload,
            )
            parsed = parse_agent_envelope(env.to_json())
            self.assertEqual(parsed.message_type, MESSAGE_TYPE_WORKER_STATUS)
            self.assertIsInstance(parsed.payload, WorkerStatusPayload)
            self.assertEqual(parsed.payload.actual_state, state)

    def test_unknown_root_fields_rejected(self) -> None:
        raw = {
            "protocol_version": 1,
            "message_type": MESSAGE_TYPE_HEARTBEAT,
            "message_id": "msg-1",
            "node_id": self.node_id,
            "sent_at": "2026-09-24T12:00:00Z",
            "payload": {"active_allocations_count": 0},
            "unauthorized_root_field": "injected_data",
        }
        with self.assertRaises(AgentMessageError) as ctx:
            parse_agent_envelope(raw)
        self.assertIn("unauthorized_root_field", str(ctx.exception))

    def test_unknown_message_type_rejected(self) -> None:
        raw = {
            "protocol_version": 1,
            "message_type": "UNKNOWN_CUSTOM_TYPE",
            "message_id": "msg-1",
            "node_id": self.node_id,
            "sent_at": "2026-09-24T12:00:00Z",
            "payload": {},
        }
        with self.assertRaises(AgentMessageError) as ctx:
            parse_agent_envelope(raw)
        self.assertIn("message_type", str(ctx.exception).lower())

    def test_invalid_active_allocation_state_rejected(self) -> None:
        # STOPPED and FAILED states are not allowed in AGENT_HELLO active_allocations
        for forbidden_state in ["STOPPED", "FAILED", "ENDED", "UNKNOWN"]:
            with self.subTest(forbidden_state=forbidden_state):
                with self.assertRaises(AgentMessageError):
                    ActiveAllocationItem(
                        allocation_id="a1",
                        attempt_id="att1",
                        local_state=forbidden_state,
                    )

    def test_token_redaction_in_repr_and_logging_path(self) -> None:
        sensitive_token = "super-secret-worker-join-token-999"
        payload = StartWorkerPayload(
            command_id="cmd-start-1",
            allocation_id="alloc-1",
            attempt_id="attempt-1",
            runtime_host="192.168.1.50",
            runtime_port=9000,
            device="cuda:0",
            initialization_seed=42,
            worker_join_token=sensitive_token,
        )
        env = AgentEnvelope(
            message_type=MESSAGE_TYPE_COMMAND,
            node_id=self.node_id,
            payload=payload,
        )

        # 1. repr() must NEVER contain raw token
        self.assertNotIn(sensitive_token, repr(payload))
        self.assertIn("***REDACTED***", repr(payload))
        self.assertNotIn(sensitive_token, repr(env))
        self.assertIn("***REDACTED***", repr(env))

        # 2. to_dict(redact=True) / to_json(redact=True) must redact token
        redacted_dict = env.to_dict(redact=True)
        self.assertEqual(redacted_dict["payload"]["worker_join_token"], "***REDACTED***")
        self.assertNotIn(sensitive_token, env.to_json(redact=True))

        # 3. to_dict(redact=False) / to_json(redact=False) preserves token for wire transmission
        wire_dict = env.to_dict(redact=False)
        self.assertEqual(wire_dict["payload"]["worker_join_token"], sensitive_token)
        self.assertIn(sensitive_token, env.to_json(redact=False))

    def test_raw_tensor_gradient_fields_strictly_forbidden(self) -> None:
        for forbidden_key in ["gradients", "gradient", "tensor", "weights", "raw_tensor"]:
            raw = {
                "protocol_version": 1,
                "message_type": MESSAGE_TYPE_RESOURCE_SNAPSHOT,
                "message_id": "msg-1",
                "node_id": self.node_id,
                "sent_at": "2026-09-24T12:00:00Z",
                "payload": {
                    "cpu_utilization_pct": 10.0,
                    "ram_used_bytes": 100,
                    "ram_total_bytes": 200,
                    "gpus": [],
                    forbidden_key: [0.1, 0.2, 0.3],
                },
            }
            with self.subTest(forbidden_key=forbidden_key):
                with self.assertRaises(AgentMessageError) as ctx:
                    parse_agent_envelope(raw)
                self.assertIn("forbidden data plane field", str(ctx.exception).lower())

    def test_invalid_command_type_rejected(self) -> None:
        raw = {
            "protocol_version": 1,
            "message_type": MESSAGE_TYPE_COMMAND,
            "message_id": "msg-1",
            "node_id": self.node_id,
            "sent_at": "2026-09-24T12:00:00Z",
            "payload": {
                "command_type": "REBOOT_NODE",
                "command_id": "cmd-1",
                "allocation_id": "a-1",
            },
        }
        with self.assertRaises(AgentMessageError) as ctx:
            parse_agent_envelope(raw)
        self.assertIn("unknown command_type", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
