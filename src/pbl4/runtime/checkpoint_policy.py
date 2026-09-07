"""Checkpoint Policy — checkpoint cadence and trigger policy.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Checkpoint policy decision and cadence evaluation.
- In V1: after_each_model_update_blocking checkpoint policy.
- Evaluating whether current state requires triggering a checkpoint gate.

MUST NOT OWN
------------
- Synchronization admission or update-readiness decisions (owned by SynchronizationPolicy).
- Checkpoint serialization or disk durability mechanism (owned by CheckpointManager).
- Attempt lifecycle orchestration or gate enforcement (owned by Coordinator).

CRITICAL V1 INVARIANTS
----------------------
- Verified V1 checkpoint policy is strictly after_each_model_update_blocking.
- SynchronizationPolicy does NOT decide checkpoint cadence.
- Model update/synchronization completion alone is NOT sufficient to progress past
  the required durability gate; checkpoint must be COMPLETE before Step COMMITTED / progression.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class CheckpointPolicy:
    """Decides when a checkpoint should be taken."""

    def __init__(self) -> None:
        raise NotImplementedError
