"""DTP/1 message concepts and application payload schemas.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- DTP/1 message concepts (HELLO, DATASET_ASSIGNMENT, STEP_START,
  GRADIENT_META, PARAMETER_META, ERROR).
- Application payload wire schema definitions and payload framing contracts.

MUST NOT OWN
------------
- Runtime synchronization transitions or worker registration state.
- Model parameter updating or aggregation execution.
- Transport socket connection handling or framing primitives.
- Checkpoint persistence schemas.

CRITICAL V1 INVARIANTS
----------------------
- DTP/1 message payloads are carried across persistent TCP connections.
- Raw gradient tensors and canonical parameter tensors travel exclusively over DTP/1.
- Numeric type codes and exact schemas derive strictly from canonical DTP/1 specification.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

# Message payload schemas will be defined strictly per canonical DTP/1 spec.
