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
- Concurrency model selection (blocking by design; threading belongs to callers).

CRITICAL V1 INVARIANTS
----------------------
- Pure TCP transport primitive with zero training-domain or protocol dependencies.

IMPLEMENTATION STATUS
---------------------
Implemented — Python stdlib blocking sockets only. TCP_NODELAY is enabled for
low-latency framed traffic; connection failures surface as TransportError.
"""

from __future__ import annotations

import contextlib
import socket

from pbl4.common.errors import TransportError


class TcpClient:
    """TCP client for connecting to a peer transport endpoint."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float | None = None,
        connect_timeout: float | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self._sock: socket.socket | None = None

    @property
    def connected(self) -> bool:
        """Whether the client currently holds an open connection."""
        return self._sock is not None

    @property
    def sock(self) -> socket.socket:
        """The connected socket; raises TransportError when not connected."""
        if self._sock is None:
            raise TransportError("TcpClient is not connected")
        return self._sock

    def connect(self) -> None:
        """Establish TCP connection to the server."""
        if self._sock is not None:
            raise TransportError("TcpClient is already connected")
        connect_timeout = self.connect_timeout if self.connect_timeout is not None else self.timeout
        try:
            sock = socket.create_connection((self.host, self.port), timeout=connect_timeout)
        except OSError as exc:
            raise TransportError(f"Failed to connect to {self.host}:{self.port}: {exc}") from exc
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(self.timeout)
        self._sock = sock

    def disconnect(self) -> None:
        """Close the TCP connection (idempotent)."""
        sock, self._sock = self._sock, None
        if sock is None:
            return
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            sock.close()
