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
- Wire sentinel values for unset worker/tensor/chunk/operation fields.
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

# ─── Sentinel values (maximum uint32/uint64 representations) ────────────────
# Sentinel: worker_id before the Runtime assigns a logical rank
UNASSIGNED_WORKER_ID: int = 0xFFFFFFFF
# Sentinel: the frame does not target a logical training operation
NO_OPERATION: int = 0xFFFFFFFFFFFFFFFF
# Sentinel: the frame does not target a tensor transfer
NO_TENSOR: int = 0xFFFFFFFF
# Sentinel: chunk_index does not refer to a concrete chunk
NO_CHUNK: int = 0xFFFFFFFF

# ─── Message type codes ─────────────────────────────────────────────────────
# Fixed by the approved DTP/1 wire specification:
MESSAGE_TYPE_HELLO: int = 0x0001
MESSAGE_TYPE_GRADIENT_META: int = 0x0021
# Provisional pending canonical confirmation (centralized for one-line fixes):
MESSAGE_TYPE_DATASET_ASSIGNMENT: int = 0x0010
MESSAGE_TYPE_STEP_START: int = 0x0011
MESSAGE_TYPE_PARAMETER_META: int = 0x0022
MESSAGE_TYPE_ERROR: int = 0x00FF

# Defensive upper bound for a single DTP payload on the wire (provisional).
DEFAULT_MAX_PAYLOAD_BYTES: int = 64 * 1024 * 1024
