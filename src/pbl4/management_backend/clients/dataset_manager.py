"""Dataset Manager client — Management Backend HTTP client to Dataset Manager.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- HTTP API communication from Management Backend to Dataset Manager.
- Initiating dataset builds, querying build progress, and fetching catalog metadata.

MUST NOT OWN
------------
- Local dataset partitioning or shard materialization (owned by Dataset Manager).
- Worker shard downloading (workers download shards directly via HTTP).
- Inferring READY state locally (readiness is only determined by Dataset Manager).

CRITICAL V1 INVARIANTS
----------------------
- Management Backend never self-infers dataset READY status; queries Dataset Manager.
- Does not proxy shard artifact downloads for workers.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class DatasetManagerClient:
    """HTTP client for Management Backend → Dataset Manager communication."""

    def __init__(self) -> None:
        raise NotImplementedError
