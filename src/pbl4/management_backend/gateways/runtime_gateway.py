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
Implemented — Python stdlib blocking sockets only. Per the dependency contract
(management_backend → management_protocol, common), this gateway owns its own
minimal byte-stream helpers instead of importing the generic transport package.
"""

from __future__ import annotations

import contextlib
import socket
import threading

from pbl4.common.errors import TransportError
from pbl4.management_protocol.codec import McpCodec
from pbl4.management_protocol.constants import DEFAULT_MAX_MESSAGE_BYTES
from pbl4.management_protocol.messages import McpEnvelope


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from sock (minimal local helper).

    management_backend must not import the generic transport package per the
    dependency contract, so this gateway owns a minimal exact-byte reader.
    """
    chunks = bytearray()
    while len(chunks) < n:
        try:
            chunk = sock.recv(n - len(chunks))
        except TimeoutError as exc:
            raise TransportError(
                f"Timed out after reading {len(chunks)} of {n} expected bytes"
            ) from exc
        except ConnectionError as exc:
            raise TransportError(f"Connection error while reading: {exc}") from exc
        if not chunk:
            raise TransportError(
                f"Peer closed the connection after {len(chunks)} of {n} expected bytes"
            )
        chunks.extend(chunk)
    return bytes(chunks)


def _send_all(sock: socket.socket, data: bytes) -> None:
    """Send all bytes in data, handling partial writes (minimal local helper)."""
    view = memoryview(data)
    total = len(view)
    sent = 0
    while sent < total:
        try:
            sent_now = sock.send(view[sent:])
        except TimeoutError as exc:
            raise TransportError(f"Timed out after sending {sent} of {total} bytes") from exc
        except ConnectionError as exc:
            raise TransportError(f"Connection error while sending: {exc}") from exc
        if sent_now <= 0:
            raise TransportError(f"Socket reported an empty send after {sent} of {total} bytes")
        sent += sent_now


class RuntimeGateway:
    """MCP/1 client connecting Management Backend to Runtime for management."""

    DEFAULT_RUNTIME_HOST = "127.0.0.1"
    DEFAULT_RUNTIME_MANAGEMENT_PORT = 9100

    def __init__(
        self,
        host: str = DEFAULT_RUNTIME_HOST,
        port: int = DEFAULT_RUNTIME_MANAGEMENT_PORT,
        *,
        timeout: float | None = None,
        connect_timeout: float | None = None,
        max_message_bytes: int = DEFAULT_MAX_MESSAGE_BYTES,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.max_message_bytes = max_message_bytes
        self._sock: socket.socket | None = None
        self._send_lock = threading.Lock()

    @property
    def connected(self) -> bool:
        """Whether the gateway currently holds an open MCP/1 connection."""
        return self._sock is not None

    def connect(self) -> None:
        """Open the outbound MCP/1 TCP connection to the Runtime endpoint."""
        if self._sock is not None:
            raise TransportError("RuntimeGateway is already connected")
        connect_timeout = self.connect_timeout if self.connect_timeout is not None else self.timeout
        try:
            sock = socket.create_connection((self.host, self.port), timeout=connect_timeout)
        except OSError as exc:
            raise TransportError(f"Failed to connect to {self.host}:{self.port}: {exc}") from exc
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.settimeout(self.timeout)
        self._sock = sock

    def close(self) -> None:
        """Close the MCP/1 connection (idempotent)."""
        sock, self._sock = self._sock, None
        if sock is None:
            return
        with contextlib.suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(OSError):
            sock.close()

    def send_message(self, envelope: McpEnvelope) -> None:
        """Serialize and send one MCP/1 envelope to Runtime."""
        data = McpCodec.encode(envelope, max_message_bytes=self.max_message_bytes)
        with self._send_lock:
            _send_all(self._require_sock(), data)

    def recv_message(self) -> McpEnvelope:
        """Read one MCP/1 envelope from Runtime (blocking until a full frame)."""
        return McpCodec.read_message(
            self._require_sock(),
            _recv_exact,
            max_message_bytes=self.max_message_bytes,
        )

    def _require_sock(self) -> socket.socket:
        if self._sock is None:
            raise TransportError("RuntimeGateway is not connected")
        return self._sock
