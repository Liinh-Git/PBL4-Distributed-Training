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
- Do NOT infer missing fields; exact field offsets derive strictly from canonical spec.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DTPHeader:
    """Scaffold shell for DTP/1 fixed 48-byte frame header.

    Exact field definitions, offsets, and bitwidths are defined in the canonical
    DTP/1 specification document.
    """

    # Implementation will mirror canonical field layout when protocol coding begins.
    pass
