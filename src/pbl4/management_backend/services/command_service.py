"""Command Service — query and lifecycle for control_commands.

Commands are created by other services (AttemptService, DatasetService).
This service provides read access and status tracking.
"""

from __future__ import annotations

import logging

import psycopg

from pbl4.management_backend.repositories import command_repository

logger = logging.getLogger(__name__)


class CommandNotFoundError(Exception):
    pass


def get_command(conn: psycopg.Connection, command_id: str) -> dict:
    row = command_repository.get_command(conn, command_id)
    if row is None:
        raise CommandNotFoundError(f"Command '{command_id}' not found.")
    return row


def list_commands(
    conn: psycopg.Connection,
    *,
    command_type: str | None = None,
    state: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[dict]:
    return command_repository.list_commands(
        conn,
        command_type=command_type,
        state=state,
        target_type=target_type,
        target_id=target_id,
        limit=limit,
        cursor=cursor,
    )
