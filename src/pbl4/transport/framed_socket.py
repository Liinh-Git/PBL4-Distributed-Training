"""Framed socket byte-stream I/O primitives.

CANONICAL REFERENCES
--------------------
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Exact-byte socket reading (recv_exact) handling partial reads.
- Complete buffer socket writing (send_all) handling partial writes.
- Socket timeouts, low-level error detection, and socket closure mechanics.

MUST NOT OWN
------------
- DTP or MCP protocol framing logic (owned by respective protocol codecs).
- Training domain semantics (Step, barrier, worker count, gradients, parameters).
- operation_id or correlation header parsing.
- Hardcoded framing assumptions (e.g. fixed length-prefixing across all protocols).

CRITICAL V1 INVARIANTS
----------------------
- Transport layer has zero imports of protocol, runtime, worker, or training packages.
- Functions operate purely on raw bytes buffers and socket primitives.

IMPLEMENTATION STATUS
---------------------
Implemented — Python stdlib blocking sockets only. Partial reads/writes are
handled internally; EOF mid-stream, timeouts, and connection errors surface
as TransportError (common.errors).
"""

from __future__ import annotations

import select
import socket
import time

from pbl4.common.errors import TransportError


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from sock.

    TCP is a byte stream: recv() may return fewer bytes than requested and
    consecutive reads may be coalesced, so this loops until exactly n bytes
    have been accumulated.

    Raises:
        TransportError: if the peer closes the connection before n bytes
            arrive, if the socket times out, or if the connection errors.
    """
    if n < 0:
        raise TransportError(f"recv_exact requires a non-negative byte count, got {n}")
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


def send_all(sock: socket.socket, data: bytes, timeout: float | None = None) -> None:
    """Send all bytes in data, handling partial writes.

    Raises:
        TransportError: if the socket times out, the connection errors, or the
            socket reports an empty send before all bytes are written.
    """
    view = memoryview(data)
    total = len(view)
    sent = 0
    deadline = (time.monotonic() + timeout) if timeout is not None else None
    while sent < total:
        if deadline is not None and hasattr(sock, "fileno"):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TransportError(f"Timed out after sending {sent} of {total} bytes")
            try:
                ready_w = select.select([], [sock], [], max(0.0, remaining))[1]
            except OSError as exc:
                raise TransportError(f"Connection error while waiting to send: {exc}") from exc
            if not ready_w:
                raise TransportError(f"Timed out after sending {sent} of {total} bytes")
        try:
            sent_now = sock.send(view[sent:])
        except TimeoutError as exc:
            raise TransportError(f"Timed out after sending {sent} of {total} bytes") from exc
        except ConnectionError as exc:
            raise TransportError(f"Connection error while sending: {exc}") from exc
        if sent_now <= 0:
            raise TransportError(f"Socket reported an empty send after {sent} of {total} bytes")
        sent += sent_now
