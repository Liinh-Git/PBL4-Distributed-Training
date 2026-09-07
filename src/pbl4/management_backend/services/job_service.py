"""Job Service — business logic and state management for training jobs.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Job registration, validation of training job definitions, and lifecycle state in PostgreSQL.
- Coordinating with ContractResolver and AttemptService for job execution.
- Querying job history and status for WebUI and CLI.

MUST NOT OWN
------------
- Attempt-level runtime orchestration (owned by Runtime Coordinator).
- Direct socket communication with Runtime or Workers.
- Raw tensor, gradient, or parameter operations.

CRITICAL V1 INVARIANTS
----------------------
- Job definitions are validated against supported training strategies and model architectures.
- Management-plane job coordination operates completely outside the training critical path.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations
