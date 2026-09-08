"""DTP/1 wire protocol constants and fixed dimensions.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Fixed wire protocol constants (MAGIC, HEADER_SIZE_BYTES, HEADER_BYTE_ORDER).
- Fixed wire field sizing (OPERATION_ID_BYTES).
- DTP/1 protocol version (DTP_PROTOCOL_VERSION).
- Wire sentinel values for unset session/worker/tensor/chunk/operation fields.
- DTP/1 message type codes.
- Defensive default upper bound for a single DTP payload.

MUST NOT OWN
------------
- Runtime synchronization policies or barrier timing.
- Expected worker counts or membership decisions.
- Database configurations or HTTP status codes.
- Checkpoint schema version (owned by Runtime durability).

CRITICAL V1 INVARIANTS
----------------------
- Fixed 48-byte header size (HEADER_SIZE_BYTES = 48).
- Big-endian network byte order (HEADER_BYTE_ORDER = "big").
- Magic identifier b"DPB4" (MAGIC = b"DPB4").
- operation_id wire representation is an 8-byte generic correlation field.

IMPLEMENTATION STATUS
---------------------
Implemented per the approved DTP/1 wire specification. HELLO (0x0001) and
GRADIENT_META (0x0021) type codes are wire-fixed; the remaining type codes are
provisional and centralized here for one-line correction if the canonical
specification assigns different values.

Endianness note: all header integers are big-endian; raw FP32 tensor payload
bytes are little-endian on the wire.
"""

from __future__ import annotations

# Magic identifier for DTP/1 frames (4 bytes)
MAGIC: bytes = b"DPB4"

# Fixed header size in bytes (48 bytes)
HEADER_SIZE_BYTES: int = 48

# Byte order for all multi-byte integer header fields
HEADER_BYTE_ORDER: str = "big"

# OperationId is a generic 8-byte correlation identifier on the wire
OPERATION_ID_BYTES: int = 8

# DTP/1 protocol version carried in every frame header
DTP_PROTOCOL_VERSION: int = 1

# ─── Sentinel values (maximum uint32/uint64 representations / unbound zero) ───
# Sentinel: session_id before the Runtime assigns an active session
UNBOUND_SESSION: int = 0
# Sentinel: worker_id before the Runtime assigns a logical rank
UNASSIGNED_WORKER_ID: int = 0xFFFFFFFF
# Sentinel: the frame does not target a logical training operation
NO_OPERATION: int = 0xFFFFFFFFFFFFFFFF
# Sentinel: the frame does not target a tensor transfer
NO_TENSOR: int = 0xFFFFFFFF
# Sentinel: chunk_index does not refer to a concrete chunk
NO_CHUNK: int = 0xFFFFFFFF

# ─── Canonical DTP/1 message type codes (03. Mô hình dữ liệu) ────────────────
# Handshake & Dataset Provisioning (0x0001 - 0x0005)
MESSAGE_TYPE_HELLO: int = 0x0001
MESSAGE_TYPE_HELLO_ACK: int = 0x0002
MESSAGE_TYPE_DATASET_ASSIGNMENT: int = 0x0003
MESSAGE_TYPE_SHARD_READY: int = 0x0004
MESSAGE_TYPE_SHARD_ERROR: int = 0x0005

# Model Initialization & Parameter Distribution (0x0010 - 0x0014)
MESSAGE_TYPE_MODEL_MANIFEST: int = 0x0010
MESSAGE_TYPE_MODEL_INIT: int = 0x0011
MESSAGE_TYPE_PARAMETER_META: int = 0x0012
MESSAGE_TYPE_PARAMETER_CHUNK: int = 0x0013
MESSAGE_TYPE_READY: int = 0x0014

# Training Loop & Gradient Synchronization (0x0020 - 0x0024)
MESSAGE_TYPE_STEP_START: int = 0x0020
MESSAGE_TYPE_GRADIENT_META: int = 0x0021
MESSAGE_TYPE_GRADIENT_CHUNK: int = 0x0022
MESSAGE_TYPE_GRADIENT_END: int = 0x0023
MESSAGE_TYPE_PARAMETER_APPLIED: int = 0x0024

# Lifecycle, Telemetry & Control (0x0030 - 0x0032, 0x00FF)
MESSAGE_TYPE_HEARTBEAT: int = 0x0030
MESSAGE_TYPE_EPOCH_END: int = 0x0031
MESSAGE_TYPE_STOP: int = 0x0032
MESSAGE_TYPE_ERROR: int = 0x00FF

# ─── Canonical Payload Size Bounds (03. Mô hình dữ liệu) ──────────────────────
# Default defensive upper bounds per message class:
# - Control / metadata JSON frames are capped at 1 MiB.
# - Raw tensor chunk frames are capped at 1 MiB by default (negotiable/configurable).
# - MCP/1 JSON has its own 4 MiB limit in pbl4.management_protocol.constants.
DEFAULT_MAX_CONTROL_PAYLOAD_BYTES: int = 1 * 1024 * 1024
DEFAULT_MAX_TENSOR_CHUNK_BYTES: int = 1 * 1024 * 1024

# Deprecated legacy alias; preserved for backward compatibility.
DEFAULT_MAX_PAYLOAD_BYTES: int = DEFAULT_MAX_CONTROL_PAYLOAD_BYTES

TENSOR_CHUNK_MESSAGE_TYPES: frozenset[int] = frozenset({
    MESSAGE_TYPE_PARAMETER_CHUNK,
    MESSAGE_TYPE_GRADIENT_CHUNK,
})


def max_payload_bytes_for(
    message_type: int,
    *,
    max_control_payload_bytes: int = DEFAULT_MAX_CONTROL_PAYLOAD_BYTES,
    max_tensor_chunk_bytes: int = DEFAULT_MAX_TENSOR_CHUNK_BYTES,
) -> int:
    """Return the canonical defensive payload limit for a given DTP message type."""
    if message_type in TENSOR_CHUNK_MESSAGE_TYPES:
        return max_tensor_chunk_bytes
    return max_control_payload_bytes

