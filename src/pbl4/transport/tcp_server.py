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
- Protocol framing or message parsing (handlers own socket usage semantics).

CRITICAL V1 INVARIANTS
----------------------
- Transport package knows nothing about training semantics, Step, or expected_workers.
- Server treats all incoming connections identically at the TCP layer.

IMPLEMENTATION STATUS
---------------------
Implemented — Python stdlib blocking sockets + threading (the concurrency model
selected for PBL4 V1). A dedicated accept-loop thread hands every accepted
socket to a fresh daemon thread running the caller-provided handler; stop()
closes the listener and all tracked client sockets.
"""

from __future__ import annotations

import contextlib
import socket
import threading
from collections.abc import Callable

from pbl4.common.errors import TransportError
from pbl4.common.logging import get_logger

logger = get_logger(__name__)


def _close_quietly(sock: socket.socket) -> None:
    """Close a socket, swallowing secondary close errors."""
    with contextlib.suppress(OSError):
        sock.close()


class TcpServer:
    """TCP server for accepting peer connections.

    Concurrency: one accept-loop thread; every accepted connection is served by
    its own daemon thread running ``handler(sock, address)``. Handler
    exceptions are logged and confined to that single connection.
    """

    def __init__(
        self,
        host: str,
        port: int,
        handler: Callable[[socket.socket, tuple[str, int]], None] | None,
        *,
        backlog: int = 128,
    ) -> None:
        self.host = host
        self.port = port
        self.handler = handler
        self.backlog = backlog
        self._sock: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._connections: dict[int, socket.socket] = {}
        self._threads: list[threading.Thread] = []
        self._next_connection_id = 0
        self._stopping = False

    @property
    def bound_address(self) -> tuple[str, int] | None:
        """Local bound (host, port); useful when started with port 0."""
        if self._sock is None:
            return None
        host, port = self._sock.getsockname()[:2]
        return (host, port)

    def start(self) -> None:
        """Bind and begin listening for connections."""
        if self.handler is None:
            raise ValueError("TcpServer requires a connection handler before start()")
        if self._sock is not None:
            raise TransportError("TcpServer is already started")
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(self.backlog)
        except OSError as exc:
            sock.close()
            raise TransportError(f"Failed to bind {self.host}:{self.port}: {exc}") from exc
        self._stopping = False
        self._sock = sock
        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="pbl4-tcp-accept", daemon=True
        )
        self._accept_thread.start()

    def stop(self) -> None:
        """Close listening socket and active client connections (idempotent)."""
        self._stopping = True
        sock, self._sock = self._sock, None
        if sock is not None:
            _close_quietly(sock)
        with self._lock:
            connections = list(self._connections.values())
            threads = list(self._threads)
            self._connections.clear()
        for client in connections:
            _close_quietly(client)
        for thread in threads:
            thread.join(timeout=2.0)
        accept_thread, self._accept_thread = self._accept_thread, None
        if accept_thread is not None and accept_thread is not threading.current_thread():
            accept_thread.join(timeout=5.0)

    def _accept_loop(self) -> None:
        sock = self._sock
        while sock is not None and not self._stopping:
            self._prune_finished_threads()
            try:
                client, address = sock.accept()
            except OSError:
                break  # Listener closed by stop().
            with self._lock:
                if self._stopping:
                    _close_quietly(client)
                    break
                connection_id = self._next_connection_id
                self._next_connection_id += 1
                self._connections[connection_id] = client
                thread = threading.Thread(
                    target=self._serve,
                    args=(connection_id, client, address),
                    name=f"pbl4-tcp-conn-{connection_id}",
                    daemon=True,
                )
                self._threads.append(thread)
                # Start while holding the lifecycle lock so stop() can never
                # observe an appended thread that has not started yet.
                thread.start()

    def _prune_finished_threads(self) -> None:
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()]

    def _serve(self, connection_id: int, client: socket.socket, address: tuple[str, int]) -> None:
        try:
            self.handler(client, address)
        except Exception:
            logger.exception("Connection handler failed for %s; closing connection", address)
        finally:
            _close_quietly(client)
            with self._lock:
                self._connections.pop(connection_id, None)
