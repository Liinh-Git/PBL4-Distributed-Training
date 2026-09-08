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
    KNOWN_MESSAGE_TYPES,
    MAGIC,
    MESSAGE_TYPE_DATASET_ASSIGNMENT,
    MESSAGE_TYPE_ERROR,
    MESSAGE_TYPE_GRADIENT_CHUNK,
    MESSAGE_TYPE_GRADIENT_END,
    MESSAGE_TYPE_GRADIENT_META,
    MESSAGE_TYPE_HEARTBEAT,
    MESSAGE_TYPE_HELLO,
    MESSAGE_TYPE_HELLO_ACK,
    MESSAGE_TYPE_MODEL_INIT,
    MESSAGE_TYPE_MODEL_MANIFEST,
    MESSAGE_TYPE_PARAMETER_APPLIED,
    MESSAGE_TYPE_PARAMETER_CHUNK,
    MESSAGE_TYPE_PARAMETER_META,
    MESSAGE_TYPE_READY,
    MESSAGE_TYPE_SHARD_ERROR,
    MESSAGE_TYPE_SHARD_READY,
    MESSAGE_TYPE_STEP_START,
    NO_CHUNK,
    NO_OPERATION,
    NO_TENSOR,
    UNASSIGNED_WORKER_ID,
    UNBOUND_SESSION,
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

    def validate_protocol(self, bound_identity: tuple[int, int] | None = None) -> None:
        """Validate V1 message class and generic connection identity patterns."""
        if self.message_type not in KNOWN_MESSAGE_TYPES:
            raise ProtocolError(f"Unknown DTP message_type 0x{self.message_type:04X}")
        if self.message_type == MESSAGE_TYPE_HELLO:
            expected = (
                UNBOUND_SESSION,
                UNASSIGNED_WORKER_ID,
                NO_OPERATION,
                NO_TENSOR,
                NO_CHUNK,
            )
            actual = (
                self.session_id,
                self.worker_id,
                self.operation_id,
                self.tensor_id,
                self.chunk_index,
            )
            if actual != expected:
                raise ProtocolError("HELLO must carry the canonical unbound identity sentinels")
            if bound_identity is not None:
                raise ProtocolError("HELLO is invalid after a connection is bound")
            return

        if self.message_type == MESSAGE_TYPE_ERROR and self.session_id == UNBOUND_SESSION:
            expected = (
                UNASSIGNED_WORKER_ID,
                NO_OPERATION,
                NO_TENSOR,
                NO_CHUNK,
            )
            actual = (
                self.worker_id,
                self.operation_id,
                self.tensor_id,
                self.chunk_index,
            )
            if actual != expected or bound_identity is not None:
                raise ProtocolError(
                    "Pre-registration ERROR must use the canonical unbound identity sentinels"
                )
            return

        if self.session_id == UNBOUND_SESSION or self.worker_id == UNASSIGNED_WORKER_ID:
            raise ProtocolError("Bound DTP messages require assigned session_id and worker_id")
        if bound_identity is not None and (self.session_id, self.worker_id) != bound_identity:
            raise ProtocolError("DTP frame does not match the bound connection identity")

        operation_messages = {
            MESSAGE_TYPE_STEP_START,
            MESSAGE_TYPE_GRADIENT_META,
            MESSAGE_TYPE_GRADIENT_CHUNK,
            MESSAGE_TYPE_GRADIENT_END,
            MESSAGE_TYPE_PARAMETER_APPLIED,
        }
        if self.message_type in operation_messages and self.operation_id == NO_OPERATION:
            raise ProtocolError("Operation-bound DTP message uses NO_OPERATION")
        no_operation_messages = {
            MESSAGE_TYPE_HELLO_ACK,
            MESSAGE_TYPE_DATASET_ASSIGNMENT,
            MESSAGE_TYPE_SHARD_READY,
            MESSAGE_TYPE_SHARD_ERROR,
            MESSAGE_TYPE_MODEL_MANIFEST,
            MESSAGE_TYPE_MODEL_INIT,
            MESSAGE_TYPE_READY,
            MESSAGE_TYPE_HEARTBEAT,
        }
        if self.message_type in no_operation_messages and self.operation_id != NO_OPERATION:
            raise ProtocolError("Non-operation DTP control message must use NO_OPERATION")

        tensor_messages = {
            MESSAGE_TYPE_PARAMETER_META,
            MESSAGE_TYPE_PARAMETER_CHUNK,
            MESSAGE_TYPE_GRADIENT_META,
            MESSAGE_TYPE_GRADIENT_CHUNK,
            MESSAGE_TYPE_GRADIENT_END,
        }
        if self.message_type in tensor_messages:
            if self.tensor_id == NO_TENSOR:
                raise ProtocolError("Tensor DTP message uses NO_TENSOR")
        elif self.tensor_id != NO_TENSOR:
            raise ProtocolError("Non-tensor DTP message must use NO_TENSOR")

        chunk_messages = {MESSAGE_TYPE_PARAMETER_CHUNK, MESSAGE_TYPE_GRADIENT_CHUNK}
        if self.message_type in chunk_messages:
            if self.chunk_index == NO_CHUNK:
                raise ProtocolError("Tensor chunk uses NO_CHUNK")
        elif self.chunk_index != NO_CHUNK:
            raise ProtocolError("Non-chunk DTP message must use NO_CHUNK")

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
