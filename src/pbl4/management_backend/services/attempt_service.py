"""Attempt Service — attempt lifecycle business logic and coordination.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Management-plane attempt lifecycle responsibilities:
  creating initial attempt records, associating resolved contracts,
  querying attempt history and current projection, and finalizing management records
  where canonical.
- Persisting and projecting canonical Runtime state and telemetry events.
- Dispatching approved management commands (launch, abort) to Runtime via RuntimeGateway (MCP/1).

MUST NOT OWN
------------
- Active Attempt execution lifecycle state transitions (Runtime / Coordinator is the live source of
  truth for execution lifecycle while an Attempt is running).
- Independently inventing or driving active Runtime state transitions.
- Raw gradient or parameter tensor handling.

CRITICAL V1 INVARIANTS
----------------------
- Runtime / Coordinator is the live source of truth for active Attempt execution lifecycle.
- Management Backend down does not interrupt active training step execution.
- Interacts with Runtime exclusively through MCP/1 gateway.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations
