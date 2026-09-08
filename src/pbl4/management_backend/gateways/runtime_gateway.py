"""Runtime Gateway — Management Backend MCP/1 client to Runtime Parameter Server.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Establishing and maintaining outbound MCP/1 connection to Runtime ManagementEndpoint.
- Dispatching management control commands (abort, query state, checkpoint triggers).
- Receiving and processing the stream of RuntimeEvents from Runtime.

MUST NOT OWN
------------
- DTP/1 training traffic or raw tensor transfers (gradients/parameters).
- Direct imports of Runtime training internals (Coordinator, CanonicalModel, etc.).
- Wire codec implementation (delegated to management_protocol.codec.McpCodec).

CRITICAL V1 INVARIANTS
----------------------
- Management Backend communicates with Runtime exclusively through MCP/1 over TCP.
- Backend downtime never stops active Runtime training execution.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class RuntimeGateway:
    """MCP/1 client connecting Management Backend to Runtime for management."""

    def __init__(self) -> None:
        raise NotImplementedError
