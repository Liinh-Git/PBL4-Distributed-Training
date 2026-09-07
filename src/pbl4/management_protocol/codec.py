"""MCP/1 wire codec — serialization and deserialization of management frames.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Framing and serialization of MCP/1 messages (length prefix and UTF-8 JSON payload).
- Deserialization and wire validation of incoming MCP/1 frames.

MUST NOT OWN
------------
- Network transport or socket I/O (delegated to transport layer).
- Runtime state machine or command execution logic.
- Management Backend service or persistence handling.

CRITICAL V1 INVARIANTS
----------------------
- MCP/1 codec is a pure wire-format parser with zero runtime, backend, or db dependencies.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class McpCodec:
    """Encode and decode MCP/1 wire messages."""

    @staticmethod
    def encode(message: object) -> bytes:
        raise NotImplementedError

    @staticmethod
    def decode(data: bytes) -> object:
        raise NotImplementedError
