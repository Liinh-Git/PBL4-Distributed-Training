"""Real PostgreSQL transactions using session-local copies of deployed table shapes.

No application rows, sequences or schemas are modified. LIKE copies CHECK and
unique constraints, but not foreign keys; FK/migration coverage belongs to the
existing persistence suite.
"""

import os
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import psycopg
import pytest
from psycopg import sql

from pbl4.management_backend import db
from pbl4.management_backend.gateways.mcp_port import FakeMcpClientPort
from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway
from pbl4.management_backend.repositories import attempt_repository
from pbl4.management_backend.services import event_ingest


@pytest.fixture
def event_database(monkeypatch):
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("PostgreSQL test connection is not configured")
    with psycopg.connect(url, autocommit=True, connect_timeout=3) as conn:
        for table in ("attempts", "events", "steps", "worker_steps"):
            conn.execute(
                sql.SQL(
                    "CREATE TEMP TABLE {} (LIKE public.{} INCLUDING CONSTRAINTS INCLUDING INDEXES)"
                ).format(sql.Identifier(table), sql.Identifier(table))
            )
        # Do not inherit an event_id default referencing the application's sequence.
        conn.execute(
            "ALTER TABLE pg_temp.events ALTER COLUMN event_id ADD GENERATED ALWAYS AS IDENTITY"
        )
        attempt_repository.create_attempt(
            conn,
            attempt_id="event-test",
            job_id="event-job",
            contract_hash="a" * 64,
            execution_mode="FRESH",
            created_at=datetime.now(UTC),
        )
        stats = SimpleNamespace(commits=0)

        @contextmanager
        def transaction():
            with conn.transaction():
                yield conn
            stats.commits += 1

        monkeypatch.setattr(db, "transaction", transaction)
        monkeypatch.setattr(event_ingest, "broadcast_runtime_event", MagicMock())
        yield conn, stats


def step_events(legacy=False):
    contribution = dict(
        worker_id=0,
        session_id=10,
        shard_id=1,
        batch_id=2,
        sample_count=64,
        loss=0.5,
        compute_ms=100.0,
    )
    if legacy:
        contribution.update(
            tensor_id=0, batch_ordinal=0, parameter_manifest_hash="a" * 64, correct_count=32
        )
    details = [
        dict(
            step_id=0,
            operation_id=0,
            training_strategy="strict_bsp",
            epoch=0,
            batch_ordinal=0,
            input_model_version=0,
        ),
        dict(
            step_id=0,
            operation_id=0,
            input_model_version=0,
            output_model_version=1,
            total_sample_count=64,
            contributions=[contribution],
        ),
        dict(step_id=0, output_model_version=1, total_sample_count=64),
    ]
    return [
        dict(
            attempt_id="event-test",
            job_id="event-job",
            runtime_event_seq=seq,
            event_type=kind,
            event_schema_version=1,
            occurred_at="2026-10-31T00:00:00+00:00",
            source_component="coordinator",
            severity="INFO",
            details=data,
        )
        for seq, (kind, data) in enumerate(
            zip(("step.started", "model.updated", "step.committed"), details, strict=True), 1
        )
    ]


@pytest.mark.parametrize("legacy", [False, True])
def test_postgres_batch_commits_history_projection_and_cursor_together(event_database, legacy):
    conn, stats = event_database
    runtime = RuntimeGateway(FakeMcpClientPort(initially_connected=True), redis_events=True)
    payloads = step_events(legacy)

    def broadcast(**payload):
        assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
        assert conn.execute("SELECT state FROM pg_temp.steps").fetchone() == ("COMMITTED",)
        assert stats.commits == 1

    event_ingest.broadcast_runtime_event.side_effect = broadcast
    assert runtime.handle_runtime_events(payloads) == 3
    assert conn.execute("SELECT count(*) FROM pg_temp.events").fetchone() == (3,)
    assert conn.execute(
        "SELECT sample_count, loss, compute_ms FROM pg_temp.worker_steps"
    ).fetchone() == (64, 0.5, 100.0)
    assert conn.execute("SELECT runtime_metadata FROM pg_temp.attempts").fetchone() == (
        {"highest_contiguous_seq": 3},
    )
    assert stats.commits == 1
    # Restart replays pending entries against the durable cursor without republishing.
    restarted = RuntimeGateway(FakeMcpClientPort(initially_connected=True), redis_events=True)
    assert restarted.handle_runtime_events(payloads) == 3
    assert conn.execute("SELECT count(*) FROM pg_temp.events").fetchone() == (3,)
    assert event_ingest.broadcast_runtime_event.call_count == 3


def test_postgres_projection_error_rolls_back_whole_batch(event_database):
    conn, stats = event_database
    runtime = RuntimeGateway(FakeMcpClientPort(initially_connected=True), redis_events=True)
    payloads = step_events()
    payloads[1]["details"]["contributions"][0]["sample_count"] = 2**40
    with pytest.raises(psycopg.errors.NumericValueOutOfRange):
        runtime.handle_runtime_events(payloads)
    for table in ("events", "steps", "worker_steps"):
        assert conn.execute(
            sql.SQL("SELECT count(*) FROM pg_temp.{}").format(sql.Identifier(table))
        ).fetchone() == (0,)
    assert conn.execute("SELECT runtime_metadata FROM pg_temp.attempts").fetchone() == (None,)
    assert stats.commits == 0
    event_ingest.broadcast_runtime_event.assert_not_called()

    assert runtime.handle_runtime_events(step_events()) == 3
    assert stats.commits == 1


def test_postgres_conflicting_duplicate_rolls_back_current_batch(event_database):
    conn, stats = event_database
    runtime = RuntimeGateway(FakeMcpClientPort(initially_connected=True), redis_events=True)
    first = step_events()[0]
    conflict = {**first, "details": {**first["details"], "input_model_version": 99}}
    with pytest.raises(event_ingest.ConflictingEventPayloadError):
        runtime.handle_runtime_events([first, conflict])
    assert conn.execute("SELECT count(*) FROM pg_temp.events").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM pg_temp.steps").fetchone() == (0,)
    assert stats.commits == 0
    event_ingest.broadcast_runtime_event.assert_not_called()


def test_postgres_100_metrics_keep_every_sample_in_one_commit(event_database):
    conn, stats = event_database
    runtime = RuntimeGateway(FakeMcpClientPort(initially_connected=True), redis_events=True)
    template = step_events()[0]
    payloads = [
        {
            **template,
            "runtime_event_seq": seq,
            "event_type": "metric.sample",
            "details": {"loss": seq / 100},
        }
        for seq in range(1, 101)
    ]
    assert runtime.handle_runtime_events(payloads) == 100
    rows = conn.execute(
        "SELECT runtime_event_seq, payload_jsonb FROM pg_temp.events ORDER BY runtime_event_seq"
    ).fetchall()
    assert rows == [(p["runtime_event_seq"], p["details"]) for p in payloads]
    assert stats.commits == 1
    assert event_ingest.broadcast_runtime_event.call_count == 100
