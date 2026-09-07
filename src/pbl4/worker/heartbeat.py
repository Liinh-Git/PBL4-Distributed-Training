"""Heartbeat Sender — worker-side periodic liveness transmitter.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Periodic transmission of worker liveness signals to Runtime Parameter Server.
- Formatting heartbeat frames with active session_id and progress state.

MUST NOT OWN
------------
- Heartbeat monitoring or timeout detection across the cluster (owned by Runtime).
- Low-level socket framing (delegated to WorkerClient / transport).
- Training loop step progression.

CRITICAL V1 INVARIANTS
----------------------
- Heartbeats include the assigned session_id from registration.
- Failure of heartbeat transmission signals connection loss to local worker state.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class HeartbeatSender:
    """Periodically sends heartbeat messages to the Runtime."""

    def __init__(self) -> None:
        raise NotImplementedError
