"""DTP/1 header and frame codec for serialization and deserialization.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Complete DTP frame composition and decomposition (header + payload framing responsibility).
- Packaging and parsing 48-byte headers and associated payload buffers.
- Structural wire validation (magic bytes verification, header bounds, payload length,
  payload CRC32 verification).

MUST NOT OWN
------------
- Header schema definition (owned by header.py; codec.py must not become a second owner
  of header schema).
- Step semantics, StrictBSP, barrier synchronization, or worker membership policy.
- Admission, staleness, or currency decisions (owned exclusively by Runtime policy).
- Socket I/O or network streaming primitives (owned by transport layer). Socket I/O is
  injected into DTPFrame.read_from/write_to as callables, keeping this package pure.

CRITICAL V1 INVARIANTS
----------------------
- Header serialization is strictly 48 bytes in network byte order (big-endian).
- Malformed magic or header length fails at codec boundary before processing.
- Payload integrity is verified via CRC32 (zlib.crc32); an empty payload carries CRC 0.

IMPLEMENTATION STATUS
---------------------
Implemented — Python stdlib only (struct + zlib). Zero framework and zero
transport imports; socket access is dependency-injected.
"""

from __future__ import annotations

import zlib
from collections.abc import Callable
from typing import Any

from pbl4.common.errors import ProtocolError
from pbl4.protocol.constants import DEFAULT_MAX_PAYLOAD_BYTES, HEADER_SIZE_BYTES
from pbl4.protocol.header import DTPHeader


class HeaderCodec:
    """Encode and decode DTP/1 fixed-size 48-byte headers."""

    @staticmethod
    def encode(header: DTPHeader) -> bytes:
        """Serialize DTPHeader to exactly 48 bytes."""
        return header.pack()

    @staticmethod
    def decode(data: bytes) -> DTPHeader:
        """Deserialize 48 bytes into a DTPHeader."""
        return DTPHeader.unpack(data)


class DTPFrame:
    """Complete DTP/1 wire frame: fixed 48-byte header plus variable payload.

    The payload is an opaque byte buffer at this layer (raw FP32 tensor chunks
    and application payload schemas are owned by their respective canonical
    specifications).
    """

    __slots__ = ("header", "payload")

    def __init__(self, header: DTPHeader, payload: bytes = b"") -> None:
        """Wrap an already-consistent header and payload without re-validation.

        Prefer ``pbl4.protocol.messages.build_frame`` for constructing frames;
        this constructor trusts the caller-supplied header fields.
        """
        self.header = header
        self.payload = payload

    def pack(self) -> bytes:
        """Serialize to header (exactly 48 bytes) followed by payload bytes."""
        return self.header.pack() + self.payload

    def write_to(self, sock: Any, send_fn: Callable[[Any, bytes], None]) -> None:
        """Push the complete frame through the injected send function."""
        send_fn(sock, self.pack())

    @classmethod
    def read_from(
        cls,
        sock: Any,
        recv_exact_fn: Callable[[Any, int], bytes],
        *,
        max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES,
    ) -> DTPFrame:
        """Read one complete frame via the injected exact-byte reader.

        Reads the 48-byte header first, then exactly ``payload_length`` bytes.

        Raises:
            ProtocolError: on malformed header or a payload length above the
                configured defensive limit.
            TransportError: propagated from ``recv_exact_fn`` on EOF/timeout.
        """
        header = DTPHeader.unpack(recv_exact_fn(sock, HEADER_SIZE_BYTES))
        if header.payload_length > max_payload_bytes:
            raise ProtocolError(
                f"DTP payload_length {header.payload_length} exceeds limit {max_payload_bytes}"
            )
        payload = recv_exact_fn(sock, header.payload_length)
        return cls._assemble(header, payload)

    @classmethod
    def unpack(cls, data: bytes) -> DTPFrame:
        """Decode a complete frame from header+payload bytes, verifying integrity.

        Raises:
            ProtocolError: on truncated input, malformed header, header/payload
                length mismatch, or CRC32 mismatch.
        """
        if len(data) < HEADER_SIZE_BYTES:
            raise ProtocolError(
                f"DTP frame truncated: {len(data)} bytes is smaller than the "
                f"{HEADER_SIZE_BYTES}-byte header"
            )
        header = DTPHeader.unpack(data[:HEADER_SIZE_BYTES])
        return cls._assemble(header, data[HEADER_SIZE_BYTES:])

    @classmethod
    def _assemble(cls, header: DTPHeader, payload: bytes) -> DTPFrame:
        if len(payload) != header.payload_length:
            raise ProtocolError(
                f"DTP payload length mismatch: header declares "
                f"{header.payload_length}, got {len(payload)}"
            )
        actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
        if actual_crc != header.payload_crc32:
            raise ProtocolError(
                f"DTP payload CRC32 mismatch: header declares "
                f"{header.payload_crc32:#010x}, computed {actual_crc:#010x}"
            )
        return cls(header, payload)
