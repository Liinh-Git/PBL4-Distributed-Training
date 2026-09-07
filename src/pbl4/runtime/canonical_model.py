"""Canonical Model — single-writer canonical model parameter state.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Canonical model parameter tensor storage and current ModelVersion tracking.
- Parameter buffer extraction for DTP/1 broadcast to workers.

MUST NOT OWN
------------
- Direct mutation by workers, synchronization policies, or coordinator.
- Framework-specific deep learning logic (zero PyTorch imports in Runtime).
- Checkpoint file I/O (owned by CheckpointManager).

CRITICAL V1 INVARIANTS
----------------------
- Controlled single-writer ownership: ONLY UpdateEngine and the checkpoint
  restore path may write to CanonicalModel.
- Workers receive read-only parameter copies; workers do NOT call optimizer.step()
  on the canonical distributed model.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class CanonicalModel:
    """Single-writer canonical model state.

    Only UpdateEngine and the restore path may write to this.
    """

    def __init__(self) -> None:
        raise NotImplementedError
