"""Shard Downloader — worker dataset shard artifact HTTP downloader.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Downloading assigned dataset shard artifacts over HTTP using location information
  resolved from the Runtime provisioning contract.
- Verifying the canonical artifact integrity chain:
  pinned root Dataset Manifest / dataset_manifest_hash
      ↓
  assigned Shard Manifest hash
      ↓
  individual physical batch SHA-256 hashes
      ↓
  local verified artifact set
      ↓
  SHARD_READY.
- Populating local ShardCache before signaling shard readiness.

MUST NOT OWN
------------
- Active training iteration data reads (training loop reads from local ShardCache).
- Dataset partitioning or preprocessing (owned by Dataset Manager).
- DTP/1 socket communications.

CRITICAL V1 INVARIANTS
----------------------
- Shard downloads occur before training enters RUNNING; NOT in the per-step training hot path.
- Once SHARD_READY, Dataset Manager is not contacted during training steps.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class ShardDownloader:
    """Downloads assigned dataset shards before training begins.

    Uses HTTP artifact provisioning from Dataset Manager.
    Only active before SHARD_READY; not in the training hot path.
    """

    def __init__(self) -> None:
        raise NotImplementedError
