"""Management Backend database connection and connection pool management.

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
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator

import psycopg
import psycopg_pool

logger = logging.getLogger(__name__)

# Module-level pool; initialized by init_pool() on application startup.
_pool: psycopg_pool.ConnectionPool | None = None


def init_pool(database_url: str, min_size: int = 1, max_size: int = 10) -> None:
    """Initialize the psycopg connection pool.

    Called once during FastAPI startup lifespan.
    """
    global _pool
    logger.info("Initializing PostgreSQL connection pool (max=%d)", max_size)
    _pool = psycopg_pool.ConnectionPool(
        conninfo=database_url,
        min_size=min_size,
        max_size=max_size,
        open=True,
        kwargs={"autocommit": False},
    )
    # Perform a quick connectivity check
    with _pool.connection() as conn:
        conn.execute("SELECT 1")
    logger.info("PostgreSQL connection pool ready")


def close_pool() -> None:
    """Close the connection pool. Called during application shutdown."""
    global _pool
    if _pool is not None:
        logger.info("Closing PostgreSQL connection pool")
        _pool.close()
        _pool = None


def get_pool() -> psycopg_pool.ConnectionPool:
    """Return the active connection pool; raise RuntimeError if not initialized."""
    if _pool is None:
        raise RuntimeError(
            "Database connection pool is not initialized. "
            "Ensure init_pool() was called during application startup."
        )
    return _pool


@contextmanager
def get_connection() -> Generator[psycopg.Connection, None, None]:
    """Acquire a connection from the pool as a context manager.

    The connection is returned to the pool on exit.
    Uses autocommit=False; caller is responsible for commit/rollback.
    """
    pool = get_pool()
    with pool.connection() as conn:
        yield conn


@contextmanager
def transaction() -> Generator[psycopg.Connection, None, None]:
    """Acquire a connection and execute within a single transaction.

    Commits on successful exit; rolls back on any exception.
    Use this for operations that must be atomic across multiple SQL statements.
    """
    with get_connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def check_health() -> bool:
    """Return True if the database pool is healthy, False otherwise.

    Does NOT raise; caller interprets the boolean.
    """
    try:
        pool = get_pool()
        with pool.connection() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Database health check failed: %s", exc)
        return False
