"""Unit tests for DTP/1 header and frame codec (exact wire + malformed input)."""

from __future__ import annotations

import unittest
import zlib

from pbl4.common.errors import ProtocolError
from pbl4.protocol.codec import DTPFrame, HeaderCodec
from pbl4.protocol.constants import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    HEADER_SIZE_BYTES,
    MESSAGE_TYPE_GRADIENT_META,
    MESSAGE_TYPE_HELLO,
    NO_CHUNK,
    NO_OPERATION,
    NO_TENSOR,
    UNASSIGNED_WORKER_ID,
)
from pbl4.protocol.header import DTPHeader
from pbl4.protocol.messages import build_frame, message_type_name
from pbl4.transport.framed_socket import recv_exact
from tests.unit.fake_sockets import ScriptedRecvSocket

# Golden bytes for a HELLO header per the approved DTP/1 wire specification:
# magic b"DPB4", version 1, type 0x0001, flags 0, session_id 1,
# worker_id UNASSIGNED (0xFFFFFFFF), operation_id NO_OPERATION (2^64-1),
# tensor_id/chunk_index sentinels, payload_length 0, payload_crc32 0.
GOLDEN_HELLO_HEADER = bytes.fromhex(
    "44504234"  # magic "DPB4"
    "0001"  # protocol_version 1
    "0001"  # message_type HELLO
    "00000000"  # flags 0
    "0000000000000001"  # session_id 1
    "FFFFFFFF"  # worker_id UNASSIGNED_WORKER_ID
    "FFFFFFFFFFFFFFFF"  # operation_id NO_OPERATION
    "FFFFFFFF"  # tensor_id NO_TENSOR
    "FFFFFFFF"  # chunk_index NO_CHUNK
    "00000000"  # payload_length 0
    "00000000"  # payload_crc32 0
)


def make_header(**overrides: object) -> DTPHeader:
    fields: dict[str, object] = {
        "magic": b"DPB4",
        "protocol_version": 1,
        "message_type": MESSAGE_TYPE_HELLO,
        "flags": 0,
        "session_id": 1,
        "worker_id": UNASSIGNED_WORKER_ID,
        "operation_id": NO_OPERATION,
        "tensor_id": NO_TENSOR,
        "chunk_index": NO_CHUNK,
        "payload_length": 0,
        "payload_crc32": 0,
    }
    fields.update(overrides)
    return DTPHeader(**fields)


class DTPHeaderTest(unittest.TestCase):
    def test_pack_matches_golden_wire_bytes(self) -> None:
        self.assertEqual(make_header().pack(), GOLDEN_HELLO_HEADER)
        self.assertEqual(len(GOLDEN_HELLO_HEADER), HEADER_SIZE_BYTES)

    def test_unpack_matches_golden_wire_bytes(self) -> None:
        header = DTPHeader.unpack(GOLDEN_HELLO_HEADER)
        self.assertEqual(header.magic, b"DPB4")
        self.assertEqual(header.protocol_version, 1)
        self.assertEqual(header.message_type, MESSAGE_TYPE_HELLO)
        self.assertEqual(header.flags, 0)
        self.assertEqual(header.session_id, 1)
        self.assertEqual(header.worker_id, UNASSIGNED_WORKER_ID)
        self.assertEqual(header.operation_id, NO_OPERATION)
        self.assertEqual(header.tensor_id, NO_TENSOR)
        self.assertEqual(header.chunk_index, NO_CHUNK)
        self.assertEqual(header.payload_length, 0)
        self.assertEqual(header.payload_crc32, 0)

    def test_pack_unpack_roundtrip_preserves_all_fields(self) -> None:
        payload = b"\x00\x01binary\xff"
        header = make_header(
            message_type=MESSAGE_TYPE_GRADIENT_META,
            session_id=7,
            worker_id=3,
            operation_id=9,
            tensor_id=1,
            chunk_index=2,
            payload_length=len(payload),
            payload_crc32=zlib.crc32(payload) & 0xFFFFFFFF,
        )
        self.assertEqual(DTPHeader.unpack(header.pack()), header)

    def test_wrong_magic_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            make_header(magic=b"XXXX").pack()
        bad = b"XXXX" + GOLDEN_HELLO_HEADER[4:]
        with self.assertRaises(ProtocolError):
            DTPHeader.unpack(bad)

    def test_unsupported_version_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            make_header(protocol_version=2).pack()
        bad = GOLDEN_HELLO_HEADER[:4] + b"\x00\x02" + GOLDEN_HELLO_HEADER[6:]
        with self.assertRaises(ProtocolError):
            DTPHeader.unpack(bad)

    def test_nonzero_flags_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            make_header(flags=1).pack()
        bad = GOLDEN_HELLO_HEADER[:8] + b"\x00\x00\x00\x01" + GOLDEN_HELLO_HEADER[12:]
        with self.assertRaises(ProtocolError):
            DTPHeader.unpack(bad)

    def test_truncated_header_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            DTPHeader.unpack(GOLDEN_HELLO_HEADER[:-1])

    def test_field_out_of_wire_range_rejected(self) -> None:
        with self.assertRaises(ProtocolError):
            make_header(session_id=2**64).pack()

    def test_header_codec_facade(self) -> None:
        header = make_header()
        self.assertEqual(HeaderCodec.encode(header), header.pack())
        self.assertEqual(HeaderCodec.decode(header.pack()), header)


class DTPFrameTest(unittest.TestCase):
    def test_frame_roundtrip(self) -> None:
        frame = build_frame(
            MESSAGE_TYPE_GRADIENT_META,
            b"0123456789",
            session_id=5,
            worker_id=2,
            operation_id=42,
            tensor_id=3,
            chunk_index=1,
        )
        data = frame.pack()
        self.assertEqual(len(data), HEADER_SIZE_BYTES + 10)
        decoded = DTPFrame.unpack(data)
        self.assertEqual(decoded.header, frame.header)
        self.assertEqual(decoded.payload, b"0123456789")

    def test_empty_payload_carries_zero_crc(self) -> None:
        frame = build_frame(MESSAGE_TYPE_HELLO, b"", session_id=1)
        self.assertEqual(frame.header.payload_length, 0)
        self.assertEqual(frame.header.payload_crc32, 0)
        self.assertEqual(DTPFrame.unpack(frame.pack()).payload, b"")

    def test_crc_mismatch_rejected(self) -> None:
        frame = build_frame(MESSAGE_TYPE_HELLO, b"hello", session_id=1)
        tampered = frame.header.pack() + b"hellO"
        with self.assertRaises(ProtocolError):
            DTPFrame.unpack(tampered)

    def test_payload_length_mismatch_rejected(self) -> None:
        header = make_header(
            payload_length=5,
            payload_crc32=zlib.crc32(b"hello") & 0xFFFFFFFF,
        )
        with self.assertRaises(ProtocolError):
            DTPFrame.unpack(header.pack() + b"abc")

    def test_read_from_assembles_across_fragments(self) -> None:
        frame = build_frame(MESSAGE_TYPE_GRADIENT_META, b"0123456789", session_id=5)
        data = frame.pack()
        sock = ScriptedRecvSocket([data[:7], data[7:30], data[30:]])
        decoded = DTPFrame.read_from(sock, recv_exact)
        self.assertEqual(decoded.header, frame.header)
        self.assertEqual(decoded.payload, b"0123456789")

    def test_read_from_rejects_oversized_payload_before_reading_body(self) -> None:
        header = make_header(payload_length=DEFAULT_MAX_PAYLOAD_BYTES + 1, payload_crc32=0)
        sock = ScriptedRecvSocket([header.pack()])
        with self.assertRaises(ProtocolError):
            DTPFrame.read_from(sock, recv_exact, max_payload_bytes=1024)

    def test_write_to_pushes_exact_bytes(self) -> None:
        captured: list[bytes] = []

        def send_fn(sock: object, data: bytes) -> None:
            captured.append(data)

        frame = build_frame(MESSAGE_TYPE_HELLO, b"abc", session_id=1)
        frame.write_to(None, send_fn)
        self.assertEqual(captured, [frame.pack()])


class MessageTypeNameTest(unittest.TestCase):
    def test_known_codes_map_to_names(self) -> None:
        self.assertEqual(message_type_name(MESSAGE_TYPE_HELLO), "HELLO")
        self.assertEqual(message_type_name(MESSAGE_TYPE_GRADIENT_META), "GRADIENT_META")

    def test_unknown_code_formats_hex(self) -> None:
        self.assertEqual(message_type_name(0x1234), "UNKNOWN(0x1234)")


if __name__ == "__main__":
    unittest.main()
