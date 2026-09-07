"""Dataset Storage — file storage backend for dataset artifacts and manifests.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Local filesystem directory layout and persistence of dataset build artifacts and manifests.
- Temporary build output isolation, artifact verification, and atomic publication boundary.
- Providing file paths and stream handlers for shard HTTP downloads.
- Calculating SHA-256 digests for stored artifacts.

MUST NOT OWN
------------
- Unilateral purge/deletion without Management Backend authorization (must not delete
  a build referenced by active management state).
- Runtime model checkpoint storage (owned by CheckpointManager in Runtime).
- PostgreSQL metadata persistence (owned by Management Backend).
- Worker local cache directories (owned by worker ShardCache).

CRITICAL V1 INVARIANTS
----------------------
- Artifacts are materialized in temporary location, verified, and atomically published.
- Artifacts are stored immutably once published and verified.
- Content digests in DatasetManifest match stored bytes exactly.
- Purge/deletion requires Management Backend precondition and authorization.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class DatasetStorage:
    """Manages file storage for dataset artifacts and shards."""

    def __init__(self) -> None:
        raise NotImplementedError
