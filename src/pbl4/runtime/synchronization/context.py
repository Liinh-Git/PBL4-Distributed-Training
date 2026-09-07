"""Strategy Context — runtime configuration context for synchronization.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Immutable carrier for resolved attempt-level synchronization parameters.
- Exposing expected_workers and training_strategy to SynchronizationPolicy implementations.

MUST NOT OWN
------------
- Worker registration or session tracking (owned by WorkerRegistry).
- Synchronization decision logic (owned by SynchronizationPolicy).
- Hard-coded default worker counts.

CRITICAL V1 INVARIANTS
----------------------
- expected_workers is resolved from the contract and supplied via StrategyContext.
- StrategyContext is immutable during an attempt session.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StrategyContext:
    """Immutable context provided to SynchronizationPolicy implementations."""

    expected_workers: int
    training_strategy: str
