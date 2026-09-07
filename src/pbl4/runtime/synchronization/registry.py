"""Strategy Registry — factory and resolution for synchronization policies.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Mapping resolved training_strategy string from StrategyContext to SynchronizationPolicy class.
- Factory instantiation of synchronization strategy instances with StrategyContext.

MUST NOT OWN
------------
- Policy execution or barrier state (owned by concrete SynchronizationPolicy).
- Worker session management (owned by WorkerRegistry).
- Contract resolution (owned by Management Backend ContractResolver).

CRITICAL V1 INVARIANTS
----------------------
- V1 officially supports "strict_bsp".
- Unsupported or unknown strategies must be rejected explicitly during validation.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations
