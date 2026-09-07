"""Gradient Store — temporary contribution storage abstraction.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Temporary in-memory storage of accepted contribution material keyed by the
  operation identity supplied by synchronization/orchestration semantics.
- Contribution lookup by operation identity.
- Clearing or lifecycle eviction of stored contributions upon operation completion.

MUST NOT OWN
------------
- Deciding contribution admission or rejection (owned by SynchronizationPolicy).
- Knowing expected_workers (supplied via StrategyContext).
- Determining barrier completion or deciding update-ready (owned by SynchronizationPolicy).
- Deciding when a Step is complete.
- Equating operation_id globally with step_id (in StrictBSP V1 operation_id maps 1:1 to
  step_id, but that belongs to policy semantics, not the generic store).
- Sample-weighted gradient aggregation arithmetic (owned by Aggregator).
- Disk durability or checkpoint writing (owned by CheckpointManager).

CRITICAL V1 INVARIANTS
----------------------
- GradientStore holds accepted contribution material without making policy decisions.
- Keyed generically by operation identity, not globally hardcoded to Step semantics.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class GradientStore:
    """Holds accepted contribution material keyed by the operation identity

    supplied by synchronization/orchestration semantics.
    """

    def __init__(self) -> None:
        raise NotImplementedError
