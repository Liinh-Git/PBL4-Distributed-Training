"""TCP server transport primitive.

CANONICAL REFERENCES
--------------------
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Binding to local network interface and port.
- Listening for and accepting incoming TCP peer connections.
- Handing off accepted raw sockets to caller-provided connection handlers.
- Server socket lifecycle, cleanup, and closure mechanics.

MUST NOT OWN
------------
- DTP/1 or MCP/1 message routing or protocol negotiation.
- Training domain semantics (Step, barrier, worker count, synchronization).
- Worker identity assignment, authentication, or session tracking.
- Concurrency model selection (asyncio vs threading intentionally not selected here).

CRITICAL V1 INVARIANTS
----------------------
- Transport package knows nothing about training semantics, Step, or expected_workers.
- Server treats all incoming connections identically at the TCP layer.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class TcpServer:
    """TCP server for accepting peer connections."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def start(self) -> None:
        """Bind and begin listening for connections."""
        raise NotImplementedError("TcpServer.start is not yet implemented")

    def stop(self) -> None:
        """Close listening socket and active client connections."""
        raise NotImplementedError("TcpServer.stop is not yet implemented")
