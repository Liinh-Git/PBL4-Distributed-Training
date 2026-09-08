"""Independent DTP/1 fixed-header and framing conformance tests."""

from __future__ import annotations

import struct
import unittest

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    DEFAULT_MAX_CONTROL_PAYLOAD_BYTES,
    DEFAULT_MAX_TENSOR_CHUNK_BYTES,
    NO_CHUNK,
    NO_OPERATION,
    NO_TENSOR,
    UNASSIGNED_WORKER_ID,
    UNBOUND_SESSION,
    MessageType,
)
from pbl4.protocol.header import DTPHeader
from pbl4.protocol.messages import build_frame
from pbl4.transport.framed_socket import recv_exact
from tests.unit.fake_sockets import ScriptedRecvSocket

GOLDEN_HELLO_HEADER = bytes.fromhex(
    "44504234"
    "0001"
    "0001"
    "00000000"
    "0000000000000000"
    "FFFFFFFF"
    "FFFFFFFFFFFFFFFF"
    "FFFFFFFF"
    "FFFFFFFF"
    "00000000"
    "00000000"
)


def hello_header(**changes: object) -> DTPHeader:
    values: dict[str, object] = {
        "magic": b"DPB4",
        "protocol_version": 1,
        "message_type": 0x0001,
        "flags": 0,
        "session_id": 0,
        "worker_id": 0xFFFFFFFF,
        "operation_id": 0xFFFFFFFFFFFFFFFF,
        "tensor_id": 0xFFFFFFFF,
        "chunk_index": 0xFFFFFFFF,
        "payload_length": 0,
        "payload_crc32": 0,
    }
    values.update(changes)
    return DTPHeader(**values)


class CanonicalConstantsTest(unittest.TestCase):
    def test_literal_catalogue(self) -> None:
        expected = {
            "HELLO": 0x0001,
            "HELLO_ACK": 0x0002,
            "DATASET_ASSIGNMENT": 0x0003,
            "SHARD_READY": 0x0004,
            "SHARD_ERROR": 0x0005,
            "MODEL_MANIFEST": 0x0010,
            "MODEL_INIT": 0x0011,
            "PARAMETER_META": 0x0012,
            "PARAMETER_CHUNK": 0x0013,
            "READY": 0x0014,
            "STEP_START": 0x0020,
            "GRADIENT_META": 0x0021,
            "GRADIENT_CHUNK": 0x0022,
            "GRADIENT_END": 0x0023,
            "PARAMETER_APPLIED": 0x0024,
            "HEARTBEAT": 0x0030,
            "EPOCH_END": 0x0031,
            "STOP": 0x0032,
            "ERROR": 0x00FF,
        }
        self.assertEqual({item.name: int(item) for item in MessageType}, expected)

    def test_literal_sentinels_and_limits(self) -> None:
        self.assertEqual(UNBOUND_SESSION, 0)
        self.assertEqual(UNASSIGNED_WORKER_ID, 0xFFFFFFFF)
        self.assertEqual(NO_OPERATION, 0xFFFFFFFFFFFFFFFF)
        self.assertEqual(NO_TENSOR, 0xFFFFFFFF)
        self.assertEqual(NO_CHUNK, 0xFFFFFFFF)
        self.assertEqual(DEFAULT_MAX_CONTROL_PAYLOAD_BYTES, 1_048_576)
        self.assertEqual(DEFAULT_MAX_TENSOR_CHUNK_BYTES, 1_048_576)


class HeaderGoldenTest(unittest.TestCase):
    def test_exact_48_byte_hello(self) -> None:
        self.assertEqual(len(GOLDEN_HELLO_HEADER), 48)
        self.assertEqual(hello_header().pack(), GOLDEN_HELLO_HEADER)
        decoded = DTPHeader.unpack(GOLDEN_HELLO_HEADER)
        decoded.validate_protocol()
        self.assertEqual(decoded.session_id, 0)

    def test_big_endian_widths_and_generic_operation(self) -> None:
        header = hello_header(
            message_type=0x0022,
            session_id=0x0102030405060708,
            worker_id=0x090A0B0C,
            operation_id=0x0D0E0F1011121314,
            tensor_id=0,
            chunk_index=0,
        )
        raw = header.pack()
        self.assertEqual(raw[12:20], bytes.fromhex("0102030405060708"))
        self.assertEqual(raw[24:32], bytes.fromhex("0D0E0F1011121314"))
        self.assertEqual(struct.unpack(">Q", raw[24:32])[0], header.operation_id)

    def test_structural_rejections(self) -> None:
        for update in ({"magic": b"FAIL"}, {"protocol_version": 2}, {"flags": 1}):
            with self.subTest(update=update), self.assertRaises(ProtocolError):
                hello_header(**update).pack()
        with self.assertRaises(ProtocolError):
            DTPHeader.unpack(GOLDEN_HELLO_HEADER[:-1])

    def test_hello_identity_pattern(self) -> None:
        for update in (
            {"session_id": 1},
            {"worker_id": 0},
            {"operation_id": 0},
            {"tensor_id": 0},
            {"chunk_index": 0},
        ):
            with self.subTest(update=update), self.assertRaises(ProtocolError):
                hello_header(**update).validate_protocol()

    def test_bound_identity_and_zero_ids(self) -> None:
        header = hello_header(
            message_type=0x0022,
            session_id=7,
            worker_id=0,
            operation_id=0,
            tensor_id=0,
            chunk_index=0,
        )
        header.validate_protocol((7, 0))
        with self.assertRaises(ProtocolError):
            header.validate_protocol((8, 0))

    def test_unknown_type_and_message_class_patterns_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            hello_header(message_type=0x7777).validate_protocol()
        with self.assertRaises(ProtocolError):
            hello_header(message_type=0x0022, session_id=1, worker_id=0).validate_protocol()


class FrameTest(unittest.TestCase):
    def test_empty_payload_crc_zero(self) -> None:
        frame = build_frame(0x0001)
        self.assertEqual(frame.header.payload_crc32, 0)
        self.assertEqual(DTPFrame.unpack(frame.pack()).payload, b"")

    def test_fragmentation_and_coalescing(self) -> None:
        first = build_frame(0x0001)
        second = build_frame(0x0030, b"{}", session_id=1, worker_id=0)
        stream = first.pack() + second.pack()
        one_byte = ScriptedRecvSocket([bytes([byte]) for byte in stream])
        self.assertEqual(DTPFrame.read_from(one_byte, recv_exact).header.message_type, 0x0001)
        self.assertEqual(DTPFrame.read_from(one_byte, recv_exact).header.message_type, 0x0030)
        coalesced = ScriptedRecvSocket([stream])
        self.assertEqual(DTPFrame.read_from(coalesced, recv_exact).header.message_type, 0x0001)
        self.assertEqual(DTPFrame.read_from(coalesced, recv_exact).header.message_type, 0x0030)

    def test_arbitrary_fragmentation(self) -> None:
        raw = build_frame(0x0030, b'{"worker_state":"READY"}', session_id=1, worker_id=0).pack()
        sizes = (3, 11, 1, 19, 7, 2, 13)
        chunks: list[bytes] = []
        offset = 0
        for size in sizes:
            chunks.append(raw[offset : offset + size])
            offset += size
        chunks.append(raw[offset:])
        decoded = DTPFrame.read_from(ScriptedRecvSocket(chunks), recv_exact)
        self.assertEqual(decoded.pack(), raw)

    def test_eof_mid_header_and_payload(self) -> None:
        with self.assertRaises(TransportError):
            DTPFrame.read_from(ScriptedRecvSocket([GOLDEN_HELLO_HEADER[:20]]), recv_exact)
        frame = build_frame(0x0030, b"hello", session_id=1, worker_id=0)
        with self.assertRaises(TransportError):
            DTPFrame.read_from(ScriptedRecvSocket([frame.header.pack(), b"he"]), recv_exact)

    def test_crc_and_length_mismatch(self) -> None:
        frame = build_frame(0x0030, b"hello", session_id=1, worker_id=0)
        with self.assertRaises(ProtocolError):
            DTPFrame.unpack(frame.header.pack() + b"hellO")
        with self.assertRaises(ProtocolError):
            DTPFrame.unpack(frame.header.pack() + b"he")

    def test_class_specific_oversize_is_rejected_before_body_read(self) -> None:
        control = hello_header(
            message_type=0x0030,
            session_id=1,
            worker_id=0,
            payload_length=11,
            payload_crc32=0,
        )
        sock = ScriptedRecvSocket([control.pack()])
        with self.assertRaises(ProtocolError):
            DTPFrame.read_from(sock, recv_exact, max_control_payload_bytes=10)
        chunk = hello_header(
            message_type=0x0022,
            session_id=1,
            worker_id=0,
            operation_id=1,
            tensor_id=1,
            chunk_index=0,
            payload_length=11,
            payload_crc32=0,
        )
        with self.assertRaises(ProtocolError):
            DTPFrame.read_from(
                ScriptedRecvSocket([chunk.pack()]), recv_exact, max_tensor_chunk_bytes=10
            )

    def test_unknown_type_rejected_before_payload_read(self) -> None:
        raw = bytearray(GOLDEN_HELLO_HEADER)
        raw[6:8] = b"\x77\x77"
        with self.assertRaises(ProtocolError):
            DTPFrame.read_from(ScriptedRecvSocket([bytes(raw)]), recv_exact)


if __name__ == "__main__":
    unittest.main()
