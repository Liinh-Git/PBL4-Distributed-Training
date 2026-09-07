"""Management Backend database connection and connection pool management.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- PostgreSQL connection pool lifecycle via psycopg (psycopg_pool.ConnectionPool).
- Database transaction management context primitives for repositories.

MUST NOT OWN
------------
- ORM models or schema reflection (SQLAlchemy, asyncpg, Alembic are prohibited).
- Direct training step synchronization or barrier coordination.
- Runtime state machine decisions.

CRITICAL V1 INVARIANTS
----------------------
- Persistence stack is PostgreSQL + psycopg using explicit SQL queries.
- Database access is strictly off the training critical path (DB down != training down).

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

# psycopg pool and transaction helper scaffolds to be implemented
# alongside database schema migrations and repository layers.
