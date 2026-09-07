"""Runtime state snapshot representation.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

Canonical responsibility:
- Captures point-in-time immutable generic state of Runtime subsystems for management queries.
- Top-level generic snapshot includes management truth:
  - Attempt lifecycle state;
  - Worker Session / membership projection;
  - Canonical model / model_version state;
  - Checkpoint state;
  - Event cursor;
  - strategy_state (discriminated strategy-owned data).

Important boundary:
- Generic Runtime snapshot must not become StrictBSP-shaped; StrictBSP-only diagnostics
  (e.g. step/barrier arrival details) belong under strategy_state, not top-level generic schema.
- Read-only reflection of internal state; does not mutate Runtime entities.

Status:
- Scaffold only.
"""

from __future__ import annotations


class RuntimeSnapshot:
    """Immutable snapshot of runtime state for management/monitoring."""

    def __init__(self) -> None:
        raise NotImplementedError
