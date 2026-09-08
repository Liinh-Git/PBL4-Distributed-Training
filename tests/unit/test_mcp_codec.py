"""Unit tests for MCP/1 codec and envelope contract (exact wire + malformed input)."""

from __future__ import annotations

import json
import struct
import unittest

from pbl4.common.errors import ProtocolError
from pbl4.management_protocol.codec import McpCodec
from pbl4.management_protocol.messages import McpEnvelope
from pbl4.transport.framed_socket import recv_exact
from tests.unit.fake_sockets import ScriptedRecvSocket


def make_envelope(**overrides: object) -> McpEnvelope:
    fields: dict[str, object] = {
        "message_type": "backend.command",
        "message_id": "msg-0001",
        "correlation_id": "op-0001",
        "sent_at": "2026-09-08T00:00:00+00:00",
        "runtime_instance_id": "runtime-1",
        "payload": {"action": "QUERY_STATE"},
    }
    fields.update(overrides)
    return McpEnvelope(**fields)


def frame_bytes(body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + body


class McpEncodeTest(unittest.TestCase):
    def test_encode_layout_is_length_prefix_plus_utf8_json(self) -> None:
        envelope = make_envelope()
        data = McpCodec.encode(envelope)
        (length,) = struct.unpack(">I", data[:4])
        body = data[4:]
        self.assertEqual(length, len(body))
        decoded = json.loads(body.decode("utf-8"))
        self.assertEqual(decoded, envelope.to_dict())
        self.assertEqual(len(decoded), 7)

    def test_encode_oversized_body_rejected(self) -> None:
        envelope = make_envelope(payload={"blob": "x" * 64})
        with self.assertRaises(ProtocolError):
            McpCodec.encode(envelope, max_message_bytes=8)


class McpDecodeTest(unittest.TestCase):
    def test_decode_roundtrip(self) -> None:
        envelope = make_envelope()
        self.assertEqual(McpCodec.decode(McpCodec.encode(envelope)), envelope)

    def test_zero_length_prefix_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            McpCodec.decode(struct.pack(">I", 0))

    def test_oversized_length_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            McpCodec.decode(frame_bytes(b"abcde"), max_message_bytes=4)

    def test_truncated_prefix_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            McpCodec.decode(b"\x00\x00")

    def test_body_length_mismatch_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            McpCodec.decode(struct.pack(">I", 5) + b"abc")

    def test_invalid_json_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            McpCodec.decode(frame_bytes(b"nope"))

    def test_non_object_root_rejected(self) -> None:
        for body in (b"[1,2]", b'"text"', b"7", b"null"):
            with self.subTest(body=body), self.assertRaises(ProtocolError):
                McpCodec.decode(frame_bytes(body))

    def test_missing_required_field_rejected(self) -> None:
        data = make_envelope().to_dict()
        del data["correlation_id"]
        with self.assertRaises(ProtocolError):
            McpCodec.decode(frame_bytes(json.dumps(data).encode("utf-8")))

    def test_wrong_protocol_version_rejected(self) -> None:
        for bad_version in (0, 2, "1", True, 1.0):
            data = make_envelope().to_dict()
            data["protocol_version"] = bad_version
            with self.subTest(version=bad_version), self.assertRaises(ProtocolError):
                McpCodec.decode(frame_bytes(json.dumps(data).encode("utf-8")))

    def test_payload_must_be_object(self) -> None:
        data = make_envelope().to_dict()
        data["payload"] = [1, 2]
        with self.assertRaises(ProtocolError):
            McpCodec.decode(frame_bytes(json.dumps(data).encode("utf-8")))

    def test_non_empty_string_fields_required(self) -> None:
        for field_name in (
            "message_type",
            "message_id",
            "sent_at",
            "runtime_instance_id",
        ):
            data = make_envelope().to_dict()
            data[field_name] = ""
            with self.subTest(field=field_name), self.assertRaises(ProtocolError):
                McpCodec.decode(frame_bytes(json.dumps(data).encode("utf-8")))

    def test_empty_correlation_id_allowed(self) -> None:
        envelope = make_envelope(correlation_id="")
        self.assertEqual(McpCodec.decode(McpCodec.encode(envelope)), envelope)

    def test_extra_fields_tolerated(self) -> None:
        data = make_envelope().to_dict()
        data["trace_id"] = "abc123"
        envelope = McpCodec.decode(frame_bytes(json.dumps(data).encode("utf-8")))
        self.assertEqual(envelope.message_id, "msg-0001")

    def test_non_ascii_payload_roundtrip(self) -> None:
        envelope = make_envelope(payload={"note": "xin chào ☕"})
        self.assertEqual(McpCodec.decode(McpCodec.encode(envelope)), envelope)


class McpReadMessageTest(unittest.TestCase):
    def test_read_message_assembles_across_fragments(self) -> None:
        data = McpCodec.encode(make_envelope())
        sock = ScriptedRecvSocket([data[:3], data[3:20], data[20:]])
        envelope = McpCodec.read_message(sock, recv_exact)
        self.assertEqual(envelope.message_id, "msg-0001")

    def test_read_message_zero_length_rejected(self) -> None:
        sock = ScriptedRecvSocket([struct.pack(">I", 0)])
        with self.assertRaises(ProtocolError):
            McpCodec.read_message(sock, recv_exact)

    def test_read_message_oversized_rejected_without_reading_body(self) -> None:
        sock = ScriptedRecvSocket([struct.pack(">I", 1024 * 1024)])
        with self.assertRaises(ProtocolError):
            McpCodec.read_message(sock, recv_exact, max_message_bytes=1024)


if __name__ == "__main__":
    unittest.main()
