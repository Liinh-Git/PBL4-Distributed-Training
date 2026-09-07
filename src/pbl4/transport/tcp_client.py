"""TCP client transport primitive.

CANONICAL REFERENCES
--------------------
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Establishing outbound TCP connections to configured peer endpoints.
- Socket lifecycle management (connection open, disconnect, socket cleanup).
- Low-level socket options and connection error detection.

MUST NOT OWN
------------
- DTP/1 framing, handshakes, or protocol message exchange.
- Worker rank, worker_id, or worker lifecycle management.
- Training semantics, gradient shipping, or parameter receipt logic.
- Concurrency model selection (asyncio vs threading intentionally not selected here).

CRITICAL V1 INVARIANTS
----------------------
- Pure TCP transport primitive with zero training-domain or protocol dependencies.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class TcpClient:
    """TCP client for connecting to a peer transport endpoint."""

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port

    def connect(self) -> None:
        """Establish TCP connection to the server."""
        raise NotImplementedError("TcpClient.connect is not yet implemented")

    def disconnect(self) -> None:
        """Close the TCP connection."""
        raise NotImplementedError("TcpClient.disconnect is not yet implemented")
