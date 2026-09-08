"""DTP/1 message concepts and application payload schemas.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- DTP/1 message concepts (HELLO, DATASET_ASSIGNMENT, STEP_START,
  GRADIENT_META, PARAMETER_META, ERROR).
- Message type code naming and frame construction convenience helpers.

MUST NOT OWN
------------
- Runtime synchronization transitions or worker registration state.
- Model parameter updating or aggregation execution.
- Transport socket connection handling or framing primitives.
- Checkpoint persistence schemas.

CRITICAL V1 INVARIANTS
----------------------
- DTP/1 message payloads are carried across persistent TCP connections.
- Raw gradient tensors and canonical parameter tensors travel exclusively over DTP/1.
- Numeric type codes and exact schemas derive strictly from canonical DTP/1 specification.

IMPLEMENTATION STATUS
---------------------
Implemented for the framing layer: frames carry opaque payload bytes here.
Per-message payload schemas (e.g. HELLO registration fields) remain governed
by the canonical DTP/1 specification and are intentionally not invented here.
"""

from __future__ import annotations

import zlib

from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    DTP_PROTOCOL_VERSION,
    MAGIC,
    MESSAGE_TYPE_DATASET_ASSIGNMENT,
    MESSAGE_TYPE_ERROR,
    MESSAGE_TYPE_GRADIENT_META,
    MESSAGE_TYPE_HELLO,
    MESSAGE_TYPE_PARAMETER_META,
    MESSAGE_TYPE_STEP_START,
    NO_CHUNK,
    NO_OPERATION,
    NO_TENSOR,
    UNASSIGNED_WORKER_ID,
)
from pbl4.protocol.header import DTPHeader

_MESSAGE_TYPE_NAMES: dict[int, str] = {
    MESSAGE_TYPE_HELLO: "HELLO",
    MESSAGE_TYPE_DATASET_ASSIGNMENT: "DATASET_ASSIGNMENT",
    MESSAGE_TYPE_STEP_START: "STEP_START",
    MESSAGE_TYPE_GRADIENT_META: "GRADIENT_META",
    MESSAGE_TYPE_PARAMETER_META: "PARAMETER_META",
    MESSAGE_TYPE_ERROR: "ERROR",
}


def message_type_name(message_type: int) -> str:
    """Human-readable name for a DTP/1 message type code."""
    return _MESSAGE_TYPE_NAMES.get(message_type, f"UNKNOWN(0x{message_type:04X})")


def build_frame(
    message_type: int,
    payload: bytes = b"",
    *,
    session_id: int,
    worker_id: int = UNASSIGNED_WORKER_ID,
    operation_id: int = NO_OPERATION,
    tensor_id: int = NO_TENSOR,
    chunk_index: int = NO_CHUNK,
    flags: int = 0,
) -> DTPFrame:
    """Build a complete DTP/1 frame, computing payload_length and CRC32.

    Payload bytes are opaque at this layer; per-message payload schemas belong
    to the canonical DTP/1 specification.
    """
    header = DTPHeader(
        magic=MAGIC,
        protocol_version=DTP_PROTOCOL_VERSION,
        message_type=message_type,
        flags=flags,
        session_id=session_id,
        worker_id=worker_id,
        operation_id=operation_id,
        tensor_id=tensor_id,
        chunk_index=chunk_index,
        payload_length=len(payload),
        payload_crc32=zlib.crc32(payload) & 0xFFFFFFFF,
    )
    return DTPFrame(header, payload)
