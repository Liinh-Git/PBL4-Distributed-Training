"""MCP/1 wire protocol constants.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Wire-level protocol constants for MCP/1.
- Frame formatting constants (e.g. 4-byte big-endian length prefix).

MUST NOT OWN
------------
- Runtime or Parameter Server implementation details.
- Management Backend service or repository imports.
- Database queries, REST status codes, or HTTP semantics.
- Raw tensor / gradient payload definitions.

CRITICAL V1 INVARIANTS
----------------------
- MCP/1 is dedicated to management, telemetry, and control signaling.
- Zero imports of runtime, management_backend, worker, torch, or database libraries.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

# MCP/1 message type and version constants TBD during implementation per canonical specification.
