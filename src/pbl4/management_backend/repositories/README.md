# Management Backend Repositories

> Database access layer for the PBL4 Management Backend.

## Architecture & Principles

1. **PostgreSQL via `psycopg`**: All persistence operations must use `psycopg` (and `psycopg_pool`) with explicit SQL.
2. **No SQLAlchemy ORM**: Introducing SQLAlchemy models, Session fixtures, or asyncpg is prohibited without an approved architectural change.
3. **Explicit Transaction Ownership**: Transaction boundaries are explicit and are chosen according to the consistency requirements of the management use case / canonical Data Model.
4. **Out of Critical Path**: The database stores management state, audit events, and catalog metadata. It is never in the training critical path.
5. **Data Ownership**:
   - Jobs and Attempts
   - Dataset metadata and build catalogs
   - Checkpoint metadata index
   - Ingested semantic events and audit logs
