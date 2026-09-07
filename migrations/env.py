"""Alembic environment configuration for PBL4 database migrations.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu (Data model: canonical PostgreSQL schema)
- 01. PostgreSQL (Persistence policy: psycopg stack, isolated off training critical path)
- 04. Cấu trúc mã nguồn (Migration tooling boundary: standalone operator tooling)

IMPORTANT ARCHITECTURAL RULES
-----------------------------
1. Canonical DSN: DATABASE_URL is the sole canonical connection string.
   This script normalizes standard PostgreSQL URLs to the SQLAlchemy psycopg3 dialect
   ('postgresql+psycopg://...') without requiring a second environment variable.
2. ORM Isolation: target_metadata is None. PBL4 Management Backend uses psycopg with
   explicit SQL queries in repositories. No SQLAlchemy ORM declarative models are used.
3. No Runtime/Backend Application Imports: This migration environment does not import
   application code from runtime, worker, dataset_manager, or management_backend.
4. No Auto-Run: Migrations are strictly operator-driven CLI tasks, never run automatically
   on application startup.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# target_metadata is None because the project uses psycopg with explicit SQL.
# Migrations are written explicitly using Alembic op and SQLAlchemy Core types.
target_metadata = None


def get_canonical_database_url() -> str:
    """Retrieve and normalize the canonical database connection URL.

    Reads DATABASE_URL directly from the process environment variables.
    Note: Alembic does NOT automatically load or parse .env files; the operator
    must explicitly export or set DATABASE_URL in the active shell environment
    prior to executing Alembic commands (e.g., export DATABASE_URL=... or
    $env:DATABASE_URL=...).

    Normalizes postgresql:// or postgres:// prefix to postgresql+psycopg://
    to ensure SQLAlchemy connects via the installed psycopg (v3) driver.
    """
    raw_url = os.getenv("DATABASE_URL")
    if not raw_url:
        # Fall back to alembic.ini if provided
        raw_url = config.get_main_option("sqlalchemy.url")

    if not raw_url:
        raise RuntimeError(
            "Database connection URL is not configured. Please export or set the "
            "DATABASE_URL environment variable in your shell (e.g. "
            "DATABASE_URL=postgresql://user:password@localhost:5432/pbl4_db). "
            "Note: Alembic does not automatically load .env files."
        )

    # Normalize to postgresql+psycopg driver dialect
    if raw_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + raw_url[len("postgresql://") :]
    if raw_url.startswith("postgres://"):
        return "postgresql+psycopg://" + raw_url[len("postgres://") :]
    return raw_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine, though
    an Engine is acceptable here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = get_canonical_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a connection
    with the context.
    """
    url = get_canonical_database_url()
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
