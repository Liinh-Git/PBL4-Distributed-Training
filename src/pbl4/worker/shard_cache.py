"""Shard Cache — local disk cache for partitioned dataset shards.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Local storage and directory structure for downloaded dataset shard files.
- Reading shard data and batches during local training loop iterations.
- Cache identity validation using canonical key:
  dataset_build_id + dataset_manifest_hash + shard_id.

MUST NOT OWN
------------
- Network downloading over HTTP (owned by ShardDownloader).
- Remote dataset catalog management (owned by Dataset Manager).
- Training batch schedule coordination (owned by Runtime BatchScheduler).

CRITICAL V1 INVARIANTS
----------------------
- After SHARD_READY, workers read exclusively from local cache.
- Local shard reading operates completely offline from Dataset Manager.
- Cache reuse requires canonical identity (dataset_build_id + dataset_manifest_hash + shard_id)
  and integrity verification; mere directory existence does NOT confer reusability.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class ShardCache:
    """Local file cache for dataset shards.

    After SHARD_READY, training reads from this cache.
    Dataset Manager is not contacted during training.
    """

    def __init__(self) -> None:
        raise NotImplementedError
