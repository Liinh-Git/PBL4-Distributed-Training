"""Command Service — asynchronous control command dispatch and tracking.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Routing canonical management commands from REST/CLI/WebUI to Runtime via RuntimeGateway.
- Tracking command lifecycle, delivery status, and idempotency in PostgreSQL.

MUST NOT OWN
------------
- Command execution inside Runtime (Runtime executes commands internally).
- Direct socket transport manipulation (delegated to RuntimeGateway / McpCodec).
- Training-step level synchronization commands (training steps are autonomous).

CRITICAL V1 INVARIANTS
----------------------
- Management commands route strictly via MCP/1 gateway.
- Training step progression does not depend on synchronous command delivery.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations
