"""Update Engine — parameter update coordinator and canonical model writer.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Execution of canonical update cycle:
  trigger Aggregator -> trigger SgdUpdater -> write CanonicalModel -> bump ModelVersion.
- Controlled single-writer mutation of CanonicalModel for training progression.

MUST NOT OWN
------------
- Synchronization admission or readiness decisions (owned by SynchronizationPolicy).
- Worker session management (owned by WorkerRegistry).
- Checkpoint persistence or restore triggering (owned by CheckpointManager / Coordinator).

CRITICAL V1 INVARIANTS
----------------------
- Only UpdateEngine and the checkpoint restore path may write to CanonicalModel.
- Parameter updates are strictly serialized.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class UpdateEngine:
    """Orchestrates: aggregate gradients → SGD update → bump model version."""

    def __init__(self) -> None:
        raise NotImplementedError
