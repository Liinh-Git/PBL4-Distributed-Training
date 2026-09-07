"""Backend repositories — PostgreSQL data access layer.

Reference: Canonical Data Model & Backend Architecture (Google Drive)

All database persistence in this layer uses `psycopg` with explicit SQL queries.
No SQLAlchemy ORM or asyncpg.
"""

from __future__ import annotations
