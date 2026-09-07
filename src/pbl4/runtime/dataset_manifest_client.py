"""Dataset Manifest Client — pre-training dataset manifest verification client.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Fetching and verifying root DatasetManifest from Dataset Manager prior to training.
- Hash and shard identity verification against resolved training contract.

MUST NOT OWN
------------
- Per-step training data access (workers read local shards directly).
- Dataset partitioning or raw data ingestion (owned by Dataset Manager).
- Worker shard downloading (workers download their own shards via HTTP).

CRITICAL V1 INVARIANTS
----------------------
- Used only during attempt initialization/provisioning; NOT in the per-step training hot path.
- Dataset Manager down (after SHARD_READY) does not stop active training.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class DatasetManifestClient:
    """Reads root manifest from Dataset Manager for verification."""

    def __init__(self) -> None:
        raise NotImplementedError
