"""Worker Registry — worker membership and session management.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Connected worker sessions, membership tracking, and logical worker_id assignment.
- Thread-safe session registration and state transitions for connected workers.
- Worker heartbeat and liveness tracking.

MUST NOT OWN
------------
- Hard-coded expected_workers policy (expected_workers is provided via StrategyContext).
- Synchronization barrier decisions (owned by SynchronizationPolicy).
- Low-level socket framing or TCP packet parsing.
- Attempt state machine transitions (owned by Coordinator).

CRITICAL V1 INVARIANTS
----------------------
- Logical worker_id (0..N-1) is assigned by Runtime during registration.
- No special shortcuts: worker_id=0 uses the identical TCP DTP/1 path as all other workers.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class WorkerRegistry:
    """Membership and session owner for connected workers."""

    def __init__(self) -> None:
        raise NotImplementedError
