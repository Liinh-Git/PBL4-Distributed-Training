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
Implemented — Python stdlib blocking sockets + threading only. Listens on TCP
(default 127.0.0.1:9100); each backend connection is served by its own thread.
Framing violations close only the offending connection; this endpoint shares
no state with the DTP/1 training path.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.common.logging import get_logger
from pbl4.management_protocol.codec import McpCodec
from pbl4.management_protocol.constants import DEFAULT_MAX_MESSAGE_BYTES
from pbl4.management_protocol.messages import McpEnvelope
from pbl4.transport.framed_socket import recv_exact, send_all
from pbl4.transport.tcp_server import TcpServer

logger = get_logger(__name__)


@dataclass
class ManagementConnection:
    """Server-side handle to one Management Backend MCP/1 connection.

    ``send_lock`` serializes writes when several runtime threads push events
    onto the same backend connection concurrently.
    """

    sock: socket.socket
    address: tuple[str, int]
    send_lock: threading.Lock = field(default_factory=threading.Lock)


class ManagementEndpoint:
    """MCP/1 endpoint for Backend ↔ Runtime communication.

    Inbound envelopes are dispatched to ``on_message``; replies and event
    streams are pushed with ``send_message``. Semantic command execution
    (Coordinator) and event buffering (EventEmitter) plug in via that handler.
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 9100

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        on_message: Callable[[ManagementConnection, McpEnvelope], None] | None = None,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    ) -> None:
        self._server = TcpServer(host, port, handler=self._handle_connection)
        self.on_message = on_message
        self.max_message_bytes = max_message_bytes

    @property
    def bound_address(self) -> tuple[str, int] | None:
        """Local bound (host, port); useful when started with port 0."""
        return self._server.bound_address

    def start(self) -> None:
        """Bind and begin accepting Management Backend connections."""
        self._server.start()

    def stop(self) -> None:
        """Stop accepting connections and close all backend connections."""
        self._server.stop()

    def send_message(self, connection: ManagementConnection, envelope: McpEnvelope) -> None:
        """Send one MCP/1 envelope to a specific backend connection."""
        with connection.send_lock:
            McpCodec.write_message(
                connection.sock,
                send_all,
                envelope,
                max_message_bytes=self.max_message_bytes,
            )

    def _handle_connection(self, sock: socket.socket, address: tuple[str, int]) -> None:
        connection = ManagementConnection(sock=sock, address=address)
        while True:
            try:
                envelope = McpCodec.read_message(
                    sock, recv_exact, max_message_bytes=self.max_message_bytes
                )
            except (ProtocolError, TransportError, OSError) as exc:
                logger.info("MCP connection %s closed: %s", address, exc)
                # TcpServer closes the socket; backend downtime never stops training.
                return
            if self.on_message is None:
                continue
            try:
                self.on_message(connection, envelope)
            except Exception:
                logger.exception("on_message handler error for %s; closing connection", address)
                return
