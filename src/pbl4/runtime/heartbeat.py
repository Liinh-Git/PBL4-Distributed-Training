"""Heartbeat Monitor — runtime-side worker liveness and failure detection.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Tracking periodic heartbeat signals received from registered worker sessions.
- Detecting worker silence / timeout thresholds.
- Notifying WorkerRegistry and Coordinator of worker disconnection.

MUST NOT OWN
------------
- Worker TCP socket lifecycle (owned by transport / ParameterServer).
- Attempt failure policy decisions (owned by Coordinator).
- Synchronization barrier decisions (owned by SynchronizationPolicy).

CRITICAL V1 INVARIANTS
----------------------
- Heartbeat tracking operates per session_id within an active attempt.
- Timeouts trigger notification to Coordinator for deterministic failure handling.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class HeartbeatMonitor:
    """Monitors worker heartbeats and detects disconnections."""

    def __init__(self) -> None:
        raise NotImplementedError
