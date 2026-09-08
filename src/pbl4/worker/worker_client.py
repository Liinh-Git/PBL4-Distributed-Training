"""Worker Client — DTP/1 network client connecting to Runtime Parameter Server.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Establishing and maintaining persistent DTP/1 TCP connection to Parameter Server.
- Transmitting HELLO, gradient payloads, and receiving parameter broadcast payloads.
- Dispatching protocol frames using DTPHeader and HeaderCodec.

MUST NOT OWN
------------
- Canonical model parameter updates or optimizer steps.
- Direct communication with Management Backend for training operations.
- Dataset shard downloading (owned by ShardDownloader via HTTP).
- Local training loop execution (owned by TrainingLoop).

CRITICAL V1 INVARIANTS
----------------------
- Worker-0 uses the identical DTP/1 TCP path as all other workers; no special-casing.
- Logical worker_id is assigned by Runtime during registration handshake.

IMPLEMENTATION STATUS
---------------------
Implemented — Python stdlib blocking sockets only. Frames are sent and received
via the DTP codec and transport primitives. HELLO is sent with the
UNASSIGNED_WORKER_ID sentinel; the assigned logical rank comes from Runtime.
Outbound writes are serialized, including one lock held across an entire
META + CHUNK* [+ END] logical tensor transfer.
"""

from __future__ import annotations

import threading
from collections.abc import Iterable

from pbl4.protocol.codec import DTPFrame
from pbl4.protocol.constants import (
    DEFAULT_MAX_PAYLOAD_BYTES,
    NO_CHUNK,
    NO_OPERATION,
    NO_TENSOR,
    UNASSIGNED_WORKER_ID,
    UNBOUND_SESSION,
)
from pbl4.protocol.messages import Hello, build_control_frame
from pbl4.transport.framed_socket import recv_exact, send_all
from pbl4.transport.tcp_client import TcpClient


class WorkerClient:
    """DTP/1 client for communicating with the Parameter Server.

    Worker-0 uses the same TCP path as every other worker.
    No special-casing for any worker index.
    """

    DEFAULT_RUNTIME_HOST = "127.0.0.1"
    DEFAULT_RUNTIME_PORT = 5000

    def __init__(
        self,
        host: str = DEFAULT_RUNTIME_HOST,
        port: int = DEFAULT_RUNTIME_PORT,
        *,
        timeout: float | None = None,
        connect_timeout: float | None = None,
    ) -> None:
        self._client = TcpClient(host, port, timeout=timeout, connect_timeout=connect_timeout)
        self._send_lock = threading.Lock()
        self._bound_identity: tuple[int, int] | None = None

    @property
    def connected(self) -> bool:
        """Whether the client currently holds an open DTP/1 connection."""
        return self._client.connected

    def connect(self) -> None:
        """Open the persistent DTP/1 TCP connection to the Parameter Server."""
        self._client.connect()

    def close(self) -> None:
        """Close the DTP/1 connection (idempotent)."""
        self._client.disconnect()
        self._bound_identity = None

    def bind_identity(self, session_id: int, worker_id: int) -> None:
        """Record the Runtime-assigned identity after a validated HELLO_ACK."""
        if session_id <= 0 or worker_id < 0 or worker_id == UNASSIGNED_WORKER_ID:
            raise ValueError("Invalid Runtime-assigned DTP identity")
        self._bound_identity = (session_id, worker_id)

    def send_frame(self, frame: DTPFrame) -> None:
        """Serialize and send one complete DTP/1 frame."""
        with self._send_lock:
            frame.write_to(self._client.sock, send_all)

    def send_transfer(self, frames: Iterable[DTPFrame]) -> None:
        """Send a complete logical tensor transaction without interleaving."""
        sequence = tuple(frames)
        if len(sequence) < 2:
            raise ValueError("A logical tensor transfer requires metadata and chunks")
        with self._send_lock:
            for frame in sequence:
                frame.write_to(self._client.sock, send_all)

    def recv_frame(self, *, max_payload_bytes: int = DEFAULT_MAX_PAYLOAD_BYTES) -> DTPFrame:
        """Read one complete DTP/1 frame (blocking until a full frame arrives)."""
        return DTPFrame.read_from(
            self._client.sock,
            recv_exact,
            max_payload_bytes=max_payload_bytes,
            bound_identity=self._bound_identity,
        )

    def send_hello(self, hello: Hello | dict[str, object]) -> None:
        """Send canonical HELLO; Runtime, never Worker, chooses session/rank."""
        message = hello if isinstance(hello, Hello) else Hello.from_dict(hello)
        self.send_frame(
            build_control_frame(
                message,
                session_id=UNBOUND_SESSION,
                worker_id=UNASSIGNED_WORKER_ID,
                operation_id=NO_OPERATION,
                tensor_id=NO_TENSOR,
                chunk_index=NO_CHUNK,
            )
        )
