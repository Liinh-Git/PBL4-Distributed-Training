"""MCP/1 wire message definitions and payload schemas.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Wire-level command, response, and event envelope schemas for MCP/1.
- Serialization-neutral data contracts between Runtime and Management Backend.

MUST NOT OWN
------------
- Network socket I/O (owned by ManagementEndpoint in Runtime and RuntimeGateway in Backend).
- PostgreSQL data persistence or REST API conversion.
- Training tensor transport (training flows exclusively over DTP/1).

CRITICAL V1 INVARIANTS
----------------------
- MCP/1 message definitions are strictly wire-format DTOs.
- No direct imports of Runtime training internals or Backend database models.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

# Message dataclasses TBD during implementation.
