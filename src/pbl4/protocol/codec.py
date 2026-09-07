"""DTP/1 header codec for frame serialization and deserialization.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Complete DTP frame composition and decomposition (header + payload framing responsibility).
- Packaging and parsing 48-byte headers and associated payload buffers.
- Structural wire validation (magic bytes verification, header bounds, payload length).

MUST NOT OWN
------------
- Header schema definition (owned by header.py; codec.py must not become a second owner
  of header schema).
- Step semantics, StrictBSP, barrier synchronization, or worker membership policy.
- Admission, staleness, or currency decisions (owned exclusively by Runtime policy).
- Socket I/O or network streaming primitives (owned by transport layer).

CRITICAL V1 INVARIANTS
----------------------
- Header serialization is strictly 48 bytes in network byte order (big-endian).
- Malformed magic or header length fails at codec boundary before processing.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

from pbl4.protocol.header import DTPHeader


class HeaderCodec:
    """Encode and decode DTP/1 fixed-size 48-byte headers."""

    @staticmethod
    def encode(header: DTPHeader) -> bytes:
        """Serialize DTPHeader to exactly 48 bytes.

        Implementation pending protocol phase.
        """
        raise NotImplementedError("HeaderCodec.encode is not yet implemented")

    @staticmethod
    def decode(data: bytes) -> DTPHeader:
        """Deserialize 48 bytes into a DTPHeader.

        Implementation pending protocol phase.
        """
        raise NotImplementedError("HeaderCodec.decode is not yet implemented")
