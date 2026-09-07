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
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

import socket


def recv_exact(sock: socket.socket, n: int) -> bytes:
    """Read exactly n bytes from sock.

    Raises:
        TransportError: if peer closes connection before n bytes arrive.
    """
    raise NotImplementedError("recv_exact is not yet implemented")


def send_all(sock: socket.socket, data: bytes) -> None:
    """Send all bytes in data, handling partial writes."""
    raise NotImplementedError("send_all is not yet implemented")
