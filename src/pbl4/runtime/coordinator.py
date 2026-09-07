"""Coordinator — training attempt lifecycle orchestrator.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Attempt lifecycle orchestration and phase transitions:
  CREATED, WAITING_WORKERS, PROVISIONING, INITIALIZING, RUNNING,
  COMPLETING, COMPLETED, FAILED, ABORTED.
- Subsystem coordination (WorkerRegistry, UpdateEngine, SynchronizationPolicy,
  CheckpointPolicy, EventEmitter).
- Enforcing the canonical execution progress gate:
  model update -> canonical parameter publication/application ack ->
  required checkpoint -> checkpoint COMPLETE -> Step COMMITTED / progression.

MUST NOT OWN
------------
- Raw socket I/O or connection-level framing (owned by ParameterServer).
- Synchronization admission or barrier state (owned by SynchronizationPolicy).
- Canonical model parameter mutation arithmetic (owned by UpdateEngine).
- Direct PostgreSQL persistence (Runtime has zero database dependencies).

CRITICAL V1 INVARIANTS
----------------------
- Synchronization/update completion alone is NOT sufficient to progress past durability gate.
- Required checkpoint must be COMPLETE before Step COMMITTED / progression.
- No blocking external I/O under internal state locks.
- Management Backend down does not interrupt active training step progression.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class Coordinator:
    """Owns the lifecycle of a training Attempt."""

    def __init__(self) -> None:
        raise NotImplementedError
