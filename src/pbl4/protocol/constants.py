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
Scaffold only. Core behavior is intentionally not implemented.
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

# Note: Protocol version and manifest schema version representations (e.g. integer vs semver)
# derive strictly from the canonical wire/schema specifications and must be taken directly
# from them during implementation.
