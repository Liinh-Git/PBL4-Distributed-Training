"""Base synchronization policy interface.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Abstract seam for distributed parameter synchronization strategies (V1: StrictBSP).
- Full canonical conceptual policy seam:
  - Initialization and configuration from StrategyContext;
  - Contribution admission evaluation (ContributionContext / admission decision);
  - Update-readiness determination;
  - Immutable UpdatePlan production for Aggregator;
  - Model publication semantics;
  - PARAMETER_APPLIED acknowledgement handling where strategy requires it;
  - Synchronization-complete lifecycle semantics;
  - Membership failure and disconnection handling;
  - Strategy snapshot and diagnostic state contribution.

MUST NOT OWN
------------
- CanonicalModel writes (only UpdateEngine and restore path write).
- Checkpoint cadence decisions (owned by CheckpointPolicy).
- Checkpoint durability mechanism (owned by CheckpointManager).
- Cluster membership or session tracking (owned by WorkerRegistry).
- Socket I/O, transport, database, or HTTP operations.

CRITICAL V1 INVARIANTS
----------------------
- expected_workers is obtained from StrategyContext, never hard-coded.
- Policy seam encompasses contribution admission through PARAMETER_APPLIED
  acknowledgement and synchronization-complete (not collapsed into admit/ready only).
- synchronization package must NOT import checkpoint, transport, db, or http modules.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

from abc import ABC


class SynchronizationPolicy(ABC):  # noqa: B024
    """Abstract base for synchronization strategies."""

    # Method signatures will be implemented strictly per canonical design docs.
    pass
