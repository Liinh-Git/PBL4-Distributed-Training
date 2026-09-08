"""Parameter Server — DTP/1 server-side TCP listener and worker connection endpoint.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- DTP/1 server-side TCP listener and worker connection lifecycle.
- Orchestrating frame dispatch and response handling using the DTP codec/transport boundaries.
- Inbound gradient payload receiving and parameter broadcast dispatching.

MUST NOT OWN
------------
- Wire framing formats, deframing rules, or tensor byte serialization (owned by protocol codec).
- Attempt lifecycle coordination state machine (owned by Coordinator).
- Synchronization, admission, or barrier decisions (owned by SynchronizationPolicy).
- Canonical model parameter updates or SGD arithmetic (owned by UpdateEngine / SgdUpdater).
- Dataset artifact construction or storage (owned by Dataset Manager).

CRITICAL V1 INVARIANTS
----------------------
- Uses the DTP codec and transport boundaries; does not independently define wire format.
- All workers connect over DTP/1 via TCP; no special in-process shortcut exists for Worker-0.
- Raw gradient tensors and canonical parameter tensors travel exclusively over DTP/1.

IMPLEMENTATION STATUS
---------------------
Implemented — Python stdlib blocking sockets + threading only. Each worker
connection is served by its own thread; frames are read/validated via the DTP
codec and dispatched to the injected ``on_frame`` handler. Semantic handling
(registration state, admission, aggregation) belongs to Coordinator /
SynchronizationPolicy / UpdateEngine and plugs in via that handler.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from pbl4.common.errors import ProtocolError, TransportError
from pbl4.common.logging import get_logger
from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    DEFAULT_MAX_CONTROL_PAYLOAD_BYTES,
    DEFAULT_MAX_TENSOR_CHUNK_BYTES,
)
from pbl4.transport.framed_socket import recv_exact, send_all
from pbl4.transport.tcp_server import TcpServer

logger = get_logger(__name__)


@dataclass
class WorkerConnection:
    """Server-side handle to one worker TCP connection.

    ``send_lock`` serializes writes when several runtime threads push frames
    onto the same worker connection concurrently.
    """

    sock: socket.socket
    address: tuple[str, int]
    send_lock: threading.Lock = field(default_factory=threading.Lock)


class ParameterServer:
    """DTP/1 TCP server handling worker connections.

    Responsibilities:
    - Accept TCP connections via transport primitives (thread per connection).
    - Read and validate DTP/1 frames; dispatch to the registered on_frame handler.
    - Send frames with per-connection write serialization.

    A framing or transport error closes only the offending connection; other
    workers keep training. An exception raised by ``on_frame`` also closes that
    connection (logged, never fatal to the server). Failure detection and
    lifecycle decisions remain Coordinator-owned (future phase).
    """

    DEFAULT_HOST = "127.0.0.1"
    DEFAULT_PORT = 5000

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        *,
        on_frame: Callable[[WorkerConnection, DTPFrame], None] | None = None,
        max_control_payload_bytes: int = DEFAULT_MAX_CONTROL_PAYLOAD_BYTES,
        max_tensor_chunk_bytes: int = DEFAULT_MAX_TENSOR_CHUNK_BYTES,
        max_payload_bytes: int | None = None,
    ) -> None:
        self._server = TcpServer(host, port, handler=self._handle_connection)
        self.on_frame = on_frame
        self.max_control_payload_bytes = max_control_payload_bytes
        self.max_tensor_chunk_bytes = max_tensor_chunk_bytes
        self.max_payload_bytes = max_payload_bytes

    @property
    def bound_address(self) -> tuple[str, int] | None:
        """Local bound (host, port); useful when started with port 0."""
        return self._server.bound_address

    def start(self) -> None:
        """Bind and begin accepting worker connections."""
        self._server.start()

    def stop(self) -> None:
        """Stop accepting connections and close all worker connections."""
        self._server.stop()

    def send_frame(self, connection: WorkerConnection, frame: DTPFrame) -> None:
        """Send one frame to a specific worker connection."""
        with connection.send_lock:
            frame.write_to(connection.sock, send_all)

    def _handle_connection(self, sock: socket.socket, address: tuple[str, int]) -> None:
        connection = WorkerConnection(sock=sock, address=address)
        while True:
            try:
                frame = DTPFrame.read_from(
                    sock,
                    recv_exact,
                    max_control_payload_bytes=self.max_control_payload_bytes,
                    max_tensor_chunk_bytes=self.max_tensor_chunk_bytes,
                    max_payload_bytes=self.max_payload_bytes,
                )
            except (ProtocolError, TransportError, OSError) as exc:
                logger.info("DTP connection %s closed: %s", address, exc)
                # TcpServer closes the socket; failure detection is Coordinator-owned.
                return
            if self.on_frame is None:
                continue
            try:
                self.on_frame(connection, frame)
            except Exception:
                logger.exception("on_frame handler error for %s; closing connection", address)
                return
