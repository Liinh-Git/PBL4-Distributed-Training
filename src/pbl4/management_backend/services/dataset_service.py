"""Dataset Service — management coordination and catalog tracking for datasets.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Managing dataset catalog metadata records in PostgreSQL.
- Initiating ingestion and partitioning jobs via DatasetManagerClient.
- Handling dataset build registration: verifying and persisting build metadata and issuing
  registration acknowledgement.
- Querying Dataset Manager for build status and providing manifest references.

MUST NOT OWN
------------
- Dataset processing, partitioning, or storage (owned by Dataset Manager).
- Self-inferring READY status (Dataset Build READY requires completed artifacts AND
  registration acknowledgement).
- Serving shard artifact files to workers.

CRITICAL V1 INVARIANTS
----------------------
- Management Backend verifies and persists registration; never infers READY locally.
- Not involved in worker shard downloads (workers download directly from Dataset Manager).

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations
