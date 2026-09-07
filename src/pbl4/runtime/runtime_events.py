"""Runtime events — semantic event envelope and schema.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Structured event envelope (RuntimeEvent) carrying attempt telemetry and phase updates.
- Sequence counter and scope tagging for correlation across management boundaries.
- Canonical correlation key: attempt_id + runtime_event_seq.

MUST NOT OWN
------------
- Outbound socket transmission or buffering (owned by EventEmitter / ManagementEndpoint).
- Ingestion and persistence in PostgreSQL (owned by Management Backend).
- Invented event type enumerations (event vocabulary derives strictly from canonical spec).

CRITICAL V1 INVARIANTS
----------------------
- runtime_event_seq is monotonically increasing within an Attempt.
- Canonical correlation key is attempt_id + runtime_event_seq.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Canonical envelope for events emitted by the Runtime."""

    attempt_id: str
    runtime_event_seq: int
    type: str
    scope: str
    payload: dict[str, Any]
