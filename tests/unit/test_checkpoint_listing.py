"""Execute checkpoint listing joins against overlapping Attempt column names."""

import sqlite3
from contextlib import contextmanager

from pbl4.management_backend.repositories.checkpoint_repository import list_checkpoints


class _ListingConnection:
    """Use an isolated SQL engine, adapting only PostgreSQL parameter/cast syntax."""

    def __init__(self, database):
        self.database = database

    @contextmanager
    def cursor(self, **_kwargs):
        class Cursor:
            def execute(_self, sql, params):
                _self.result = self.database.execute(
                    sql.replace("%s", "?").replace("::timestamptz", ""), params
                )

            def fetchall(_self):
                return _self.result.fetchall()

        yield Cursor()


def test_complete_checkpoints_are_job_scoped_and_paginated_without_ambiguous_columns():
    with sqlite3.connect(":memory:") as database:
        database.row_factory = sqlite3.Row
        database.executescript("""
            CREATE TABLE attempts (attempt_id TEXT, job_id TEXT, state TEXT, created_at TEXT);
            CREATE TABLE checkpoints (
                checkpoint_id TEXT, created_by_attempt_id TEXT, state TEXT, created_at TEXT
            );
            INSERT INTO attempts VALUES
                ('attempt-1', 'job-1', 'FAILED', '2026-10-26T00:00:00Z'),
                ('attempt-2', 'job-2', 'COMPLETED', '2026-10-26T00:00:00Z');
            INSERT INTO checkpoints VALUES
                ('new', 'attempt-1', 'COMPLETE', '2026-10-26T02:00:00Z'),
                ('old', 'attempt-1', 'COMPLETE', '2026-10-26T01:00:00Z'),
                ('writing', 'attempt-1', 'WRITING', '2026-10-26T03:00:00Z'),
                ('other', 'attempt-2', 'COMPLETE', '2026-10-26T04:00:00Z');
        """)
        conn = _ListingConnection(database)
        first = list_checkpoints(conn, job_id="job-1", state="COMPLETE", limit=1)
        assert [row["checkpoint_id"] for row in first] == ["new"]
        assert first[0]["job_id"] == "job-1"
        second = list_checkpoints(
            conn,
            job_id="job-1",
            attempt_id="attempt-1",
            state="COMPLETE",
            cursor=f"{first[0]['created_at']}|{first[0]['checkpoint_id']}",
        )
        assert [row["checkpoint_id"] for row in second] == ["old"]
