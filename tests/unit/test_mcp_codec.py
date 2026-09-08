"""Canonical MCP/1 framing, schemas, correlation and event mapping tests."""

from __future__ import annotations

import json
import struct
import unittest
from dataclasses import dataclass, field

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.management_protocol.codec import McpCodec
from pbl4.management_protocol.messages import (
    CommandResult,
    CorrelationTracker,
    McpEnvelope,
    RuntimeEvent,
    StartAttempt,
    runtime_event_envelope,
)
from pbl4.transport.framed_socket import recv_exact
from tests.unit.fake_sockets import ScriptedRecvSocket


def envelope(
    message_type: str = "GET_STATE",
    payload: dict[str, object] | None = None,
    *,
    message_id: str = "msg-1",
    correlation_id: str | None = None,
    runtime_instance_id: str | None = "runtime-1",
) -> McpEnvelope:
    return McpEnvelope(
        message_type=message_type,
        message_id=message_id,
        correlation_id=correlation_id,
        sent_at="2026-09-08T00:00:00Z",
        runtime_instance_id=runtime_instance_id,
        payload={} if payload is None else payload,
    )


def frame(body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + body


class FramingAndEnvelopeTest(unittest.TestCase):
    def test_exact_prefix_and_roundtrip(self) -> None:
        item = envelope()
        encoded = McpCodec.encode(item)
        self.assertEqual(encoded[:4], struct.pack(">I", len(encoded) - 4))
        self.assertEqual(McpCodec.decode(encoded), item)
        self.assertIsNone(json.loads(encoded[4:])["correlation_id"])

    def test_fragmentation_and_coalescing(self) -> None:
        first = McpCodec.encode(envelope(message_id="one"))
        second = McpCodec.encode(envelope(message_id="two"))
        stream = first + second
        one_byte = ScriptedRecvSocket([bytes([byte]) for byte in stream])
        self.assertEqual(McpCodec.read_message(one_byte, recv_exact).message_id, "one")
        self.assertEqual(McpCodec.read_message(one_byte, recv_exact).message_id, "two")
        coalesced = ScriptedRecvSocket([stream])
        self.assertEqual(McpCodec.read_message(coalesced, recv_exact).message_id, "one")
        self.assertEqual(McpCodec.read_message(coalesced, recv_exact).message_id, "two")

    def test_eof_mid_prefix_and_body(self) -> None:
        with self.assertRaises(TransportError):
            McpCodec.read_message(ScriptedRecvSocket([b"\x00\x00"]), recv_exact)
        encoded = McpCodec.encode(envelope())
        with self.assertRaises(TransportError):
            McpCodec.read_message(ScriptedRecvSocket([encoded[:4], encoded[4:10]]), recv_exact)

    def test_malformed_zero_oversize_nonobject_and_nonfinite(self) -> None:
        bad_frames = [
            b"\x00\x00",
            struct.pack(">I", 0),
            frame(b"nope"),
            frame(b"[]"),
        ]
        for raw in bad_frames:
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                McpCodec.decode(raw)
        with self.assertRaises(ProtocolError):
            McpCodec.decode(frame(b"{}"), max_message_bytes=1)
        body = envelope().to_dict()
        body["payload"] = {"value": float("nan")}
        with self.assertRaises(ProtocolError):
            McpCodec.decode(frame(json.dumps(body).encode()))

    def test_nullable_context_rules(self) -> None:
        hello = envelope(
            "MGMT_HELLO",
            {"backend_instance_id": "backend", "supported_protocol_versions": [1]},
            runtime_instance_id=None,
        )
        self.assertIsNone(hello.runtime_instance_id)
        event = envelope(
            "RUNTIME_EVENT",
            {
                "attempt_id": "a",
                "job_id": "j",
                "runtime_event_seq": 1,
                "event_type": "model.updated",
                "event_schema_version": 1,
                "occurred_at": "2026-09-08T00:00:00Z",
                "source_component": "coordinator",
                "severity": "INFO",
                "details": {},
            },
        )
        self.assertIsNone(event.correlation_id)
        with self.assertRaises(ProtocolError):
            envelope("GET_STATE", correlation_id="request")
        with self.assertRaises(ProtocolError):
            envelope("STATE_SNAPSHOT", {}, correlation_id=None)
        with self.assertRaises(ProtocolError):
            envelope("GET_STATE", runtime_instance_id=None)
        with self.assertRaises(ProtocolError):
            envelope("GET_STATE", correlation_id="")

    def test_unknown_message_and_extra_envelope_field_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            envelope("backend.command")
        data = envelope().to_dict()
        data["trace_id"] = "not-v1"
        with self.assertRaises(ProtocolError):
            McpEnvelope.from_dict(data)


class PayloadSchemaTest(unittest.TestCase):
    def test_command_result_status_and_noop_rules(self) -> None:
        base = {
            "command_id": "c",
            "target_type": "ATTEMPT",
            "target_id": "a",
            "status": "SUCCEEDED",
            "result_code": "NO_OP",
            "message": "done",
            "attempt_id": "a",
            "effective_at": "2026-09-08T00:00:00Z",
            "completed_at": "2026-09-08T00:00:01Z",
        }
        CommandResult.from_dict(base)
        for status in ("PENDING", "NO_OP"):
            bad = dict(base)
            bad["status"] = status
            with self.assertRaises(ProtocolError):
                CommandResult.from_dict(bad)
        bad = dict(base)
        bad["status"] = "ACCEPTED"
        with self.assertRaises(ProtocolError):
            CommandResult.from_dict(bad)

    def test_command_id_is_payload_identity_not_message_id(self) -> None:
        result = envelope(
            "COMMAND_RESULT",
            {
                "command_id": "command-7",
                "target_type": "ATTEMPT",
                "target_id": "a",
                "status": "ACCEPTED",
                "result_code": "START_DISPATCHED",
                "message": "ok",
                "attempt_id": "a",
                "effective_at": "2026-09-08T00:00:00Z",
                "completed_at": None,
            },
            message_id="wire-9",
            correlation_id="wire-request",
        )
        self.assertNotEqual(result.message_id, result.payload.command_id)

    def test_start_attempt_execution_mode_and_raw_tensor_rejected(self) -> None:
        base = {
            "command_id": "c",
            "job_id": "j",
            "attempt_id": "a",
            "execution_mode": "FRESH",
            "resolved_contract": {"schema_version": 1},
            "contract_hash": "hash",
            "resume_from_checkpoint_id": None,
            "requested_at": "2026-09-08T00:00:00Z",
        }
        StartAttempt.from_dict(base)
        bad = dict(base)
        bad["execution_mode"] = "fresh"
        with self.assertRaises(ProtocolError):
            StartAttempt.from_dict(bad)
        bad = dict(base)
        bad["resolved_contract"] = {"gradient_bytes": "forbidden"}
        with self.assertRaises(ProtocolError):
            StartAttempt.from_dict(bad)

    def test_runtime_event_required_fields_and_severity(self) -> None:
        base = {
            "attempt_id": "a",
            "job_id": "j",
            "runtime_event_seq": 1,
            "event_type": "model.updated",
            "event_schema_version": 1,
            "occurred_at": "2026-09-08T00:00:00Z",
            "source_component": "coordinator",
            "severity": "INFO",
            "details": {},
        }
        RuntimeEvent.from_dict(base)
        for name, value in (("severity", "DEBUG"), ("runtime_event_seq", 0)):
            bad = dict(base)
            bad[name] = value
            with self.assertRaises(ProtocolError):
                RuntimeEvent.from_dict(bad)


class CorrelationAndMappingTest(unittest.TestCase):
    def test_unsolicited_event_can_interleave_request_and_result(self) -> None:
        tracker = CorrelationTracker()
        request = envelope("GET_STATE", message_id="request")
        tracker.register_request(request)
        event = envelope(
            "RUNTIME_EVENT",
            {
                "attempt_id": "a",
                "job_id": "j",
                "runtime_event_seq": 1,
                "event_type": "worker.registered",
                "event_schema_version": 1,
                "occurred_at": "2026-09-08T00:00:00Z",
                "source_component": "runtime",
                "severity": "INFO",
                "details": {},
            },
            message_id="event",
        )
        self.assertIsNone(tracker.accept(event))
        snapshot_payload = {
            "runtime_instance_id": "runtime-1",
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
            "last_runtime_event_seq": 1,
            "management_event_gap_count": 0,
            "captured_at": "2026-09-08T00:00:01Z",
        }
        response = envelope(
            "STATE_SNAPSHOT",
            snapshot_payload,
            message_id="response",
            correlation_id="request",
        )
        self.assertEqual(tracker.accept(response), "GET_STATE")

    def test_runtime_event_mapper_preserves_semantics(self) -> None:
        @dataclass
        class FakeEvent:
            attempt_id: str = "a"
            job_id: str = "j"
            runtime_event_seq: int = 2
            event_type: str = "model.updated"
            event_schema_version: int = 1
            occurred_at: str = "2026-09-08T00:00:00Z"
            source_component: str = "coordinator"
            severity: str = "INFO"
            details: dict[str, object] = field(default_factory=lambda: {"model_version": 3})

        mapped = runtime_event_envelope(
            FakeEvent(),
            message_id="wire",
            sent_at="2026-09-08T00:00:01Z",
            runtime_instance_id="runtime-1",
        )
        self.assertEqual(mapped.payload.runtime_event_seq, 2)
        self.assertIsNone(mapped.correlation_id)


if __name__ == "__main__":
    unittest.main()
