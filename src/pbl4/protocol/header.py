"""DTP/1 fixed-size frame header definition.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- DTPHeader structural representation.
- Header pack/unpack and structural validation responsibility.
- Fixed 48-byte binary frame header structure definition.

MUST NOT OWN
------------
- Complete DTP frame composition/decomposition (owned by codec.py).
- Runtime synchronization or admission decisions.
- Step numbering semantics (operation_id is generic correlation, not globally Step).
- Expected worker counts or cluster topology.

CRITICAL V1 INVARIANTS
----------------------
- Exactly 48 bytes on the wire.
- Big-endian byte order for multi-byte integers.
- Magic bytes b"DPB4".
- operation_id is an 8-byte generic correlation identifier.
- Malformed magic, unsupported version, or non-zero flags fail at the header boundary.

IMPLEMENTATION STATUS
---------------------
Implemented per the approved DTP/1 wire specification (48-byte layout below).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from pbl4.common.errors import ProtocolError
from pbl4.protocol.constants import (
    DTP_PROTOCOL_VERSION,
    HEADER_BYTE_ORDER,
    HEADER_SIZE_BYTES,
    MAGIC,
)

# Field layout (approved DTP/1 wire specification), in exact wire order:
#   magic 4s | protocol_version H | message_type H | flags I | session_id Q |
#   worker_id I | operation_id Q | tensor_id I | chunk_index I |
#   payload_length I | payload_crc32 I                      => 48 bytes total.
_BYTE_ORDER_PREFIX = {"big": ">", "little": "<"}[HEADER_BYTE_ORDER]
_HEADER_STRUCT = struct.Struct(_BYTE_ORDER_PREFIX + "4sHHIQIQIIII")

if _HEADER_STRUCT.size != HEADER_SIZE_BYTES:
    raise RuntimeError(
        f"DTP header layout is {_HEADER_STRUCT.size} bytes; wire spec requires {HEADER_SIZE_BYTES}"
    )


@dataclass(frozen=True, slots=True)
class DTPHeader:
    """DTP/1 fixed 48-byte frame header.

    Field order matches the wire layout exactly (see ``_HEADER_STRUCT``).
    """

    magic: bytes
    protocol_version: int
    message_type: int
    flags: int
    session_id: int
    worker_id: int
    operation_id: int
    tensor_id: int
    chunk_index: int
    payload_length: int
    payload_crc32: int

    def pack(self) -> bytes:
        """Serialize to exactly 48 bytes in network byte order.

        Raises:
            ProtocolError: if magic, protocol_version, or flags violate the
                wire specification, or any field exceeds its wire width.
        """
        if self.magic != MAGIC:
            raise ProtocolError(f"Invalid DTP magic {self.magic!r}; expected {MAGIC!r}")
        if self.protocol_version != DTP_PROTOCOL_VERSION:
            raise ProtocolError(
                f"Unsupported DTP protocol_version {self.protocol_version}; "
                f"expected {DTP_PROTOCOL_VERSION}"
            )
        if self.flags != 0:
            raise ProtocolError(f"DTP flags must be 0, got {self.flags}")
        try:
            return _HEADER_STRUCT.pack(
                self.magic,
                self.protocol_version,
                self.message_type,
                self.flags,
                self.session_id,
                self.worker_id,
                self.operation_id,
                self.tensor_id,
                self.chunk_index,
                self.payload_length,
                self.payload_crc32,
            )
        except struct.error as exc:
            raise ProtocolError(f"DTP header field out of wire range: {exc}") from exc

    @classmethod
    def unpack(cls, data: bytes) -> DTPHeader:
        """Deserialize and structurally validate exactly 48 header bytes.

        Raises:
            ProtocolError: on wrong size, malformed magic, unsupported
                protocol version, or non-zero flags.
        """
        if len(data) != HEADER_SIZE_BYTES:
            raise ProtocolError(
                f"DTP header must be exactly {HEADER_SIZE_BYTES} bytes, got {len(data)}"
            )
        (
            magic,
            protocol_version,
            message_type,
            flags,
            session_id,
            worker_id,
            operation_id,
            tensor_id,
            chunk_index,
            payload_length,
            payload_crc32,
        ) = _HEADER_STRUCT.unpack(data)
        if magic != MAGIC:
            raise ProtocolError(f"Invalid DTP magic {magic!r}; expected {MAGIC!r}")
        if protocol_version != DTP_PROTOCOL_VERSION:
            raise ProtocolError(
                f"Unsupported DTP protocol_version {protocol_version}; "
                f"expected {DTP_PROTOCOL_VERSION}"
            )
        if flags != 0:
            raise ProtocolError(f"DTP flags must be 0, got {flags}")
        return cls(
            magic=magic,
            protocol_version=protocol_version,
            message_type=message_type,
            flags=flags,
            session_id=session_id,
            worker_id=worker_id,
            operation_id=operation_id,
            tensor_id=tensor_id,
            chunk_index=chunk_index,
            payload_length=payload_length,
            payload_crc32=payload_crc32,
        )
