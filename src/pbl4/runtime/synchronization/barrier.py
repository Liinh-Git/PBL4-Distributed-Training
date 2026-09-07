"""Barrier — internal step-synchronization primitive for StrictBSP.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Tracking contribution arrivals for the current step iteration within StrictBSP.
- Signaling when all expected_workers contributions have arrived.
- Barrier lifecycle and reset mechanics across step iterations.

MUST NOT OWN
------------
- Generic Runtime orchestration (Barrier is strictly an INTERNAL StrictBSP primitive).
- Checkpoint cadence decisions or durability (owned by CheckpointPolicy / CheckpointManager).
- Model parameter updating (owned by UpdateEngine).
- Socket I/O or network handling.

CRITICAL V1 INVARIANTS
----------------------
- The Barrier is private to StrictBSP and must not be used as a generic Runtime primitive.
- Releases only when exactly expected_workers valid contributions have arrived for the step.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class Barrier:
    """Internal step-synchronization barrier for StrictBSP."""

    # Implementation pending StrictBSP phase.
    pass
