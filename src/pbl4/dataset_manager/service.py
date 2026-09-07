"""Dataset Service — core orchestration service for dataset builds and shard delivery.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Orchestrating the Dataset Build lifecycle: import -> preprocess -> partition ->
  materialization/verification -> canonical manifest publication ->
  registration with Management Backend -> READY upon registration acknowledgement.
- Serving shard artifact files to workers via HTTP.

MUST NOT OWN
------------
- Runtime training synchronization, barriers, or gradient handling.
- Canonical model parameter states or updates.
- Worker registration or session membership.

CRITICAL V1 INVARIANTS
----------------------
- A Dataset Build may become READY only after required artifact work is complete AND
  management registration has been successfully acknowledged by Management Backend.
  Publish/verify alone is NOT sufficient for READY; registration acknowledgement
  is part of the READY gate.
- After all worker shards are ready, Dataset Manager is off the training-step hot path.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class DatasetService:
    """Core business logic for dataset management."""

    def __init__(self) -> None:
        raise NotImplementedError
