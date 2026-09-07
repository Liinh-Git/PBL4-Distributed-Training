"""Event Ingest Service — ingests and persists runtime events into PostgreSQL.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Ingesting incoming RuntimeEvents received over the MCP/1 gateway connection.
- Persisting structured events and audit records into PostgreSQL using psycopg.
- Broadcasting ingested events to live WebUI WebSocket subscribers.

MUST NOT OWN
------------
- Runtime event generation or buffering (owned by Runtime EventEmitter).
- MCP/1 socket listening (owned by Runtime ManagementEndpoint).
- Synchronization barrier decisions.

CRITICAL V1 INVARIANTS
----------------------
- Event ingestion delays or database latency MUST NOT block Runtime training steps.
- DB down != training down (training progresses independently of event ingestion).

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations
