"""Management Endpoint — Runtime-side MCP/1 server endpoint.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Runtime-side MCP/1 TCP listener and management connection lifecycle.
- Ingestion and dispatch of incoming management commands from Management Backend.
- Streaming runtime events (buffered by EventEmitter) to Management Backend.

MUST NOT OWN
------------
- MCP/1 wire codec or message schema definitions (owned by management_protocol).
- Attempt lifecycle decisions (owned by Coordinator).
- Direct database access (Management Backend owns persistence).
- DTP/1 training traffic (Parameter Server owns DTP/1).

CRITICAL V1 INVARIANTS
----------------------
- Management control traffic is isolated from DTP/1 training traffic.
- Management Backend down does not interrupt active training step execution.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class ManagementEndpoint:
    """MCP/1 endpoint for Backend ↔ Runtime communication."""

    def __init__(self) -> None:
        raise NotImplementedError
