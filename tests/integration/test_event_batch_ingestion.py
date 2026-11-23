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
        for table in ("attempts", "events", "steps", "worker_steps", "checkpoints"):
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
        monkeypatch.setattr(
            event_ingest,
            "broadcast_runtime_event",
            MagicMock(wraps=event_ingest.broadcast_runtime_event),
        )
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


@pytest.mark.parametrize("first_snapshot", [200, None, 99, 101, "projection_error", "commit_error"])
def test_mcp_gap_projects_checkpoint_history_after_commit(
    event_database, monkeypatch, first_snapshot
):
    from pbl4.management_backend.tests.test_runtime_gateway import _valid_snapshot_dict
    from pbl4.management_backend.websocket import hub

    conn, _ = event_database
    port = FakeMcpClientPort(initially_connected=True)
    gateway = RuntimeGateway(port, redis_events=False)
    cursor = gateway.get_cursor("event-test")
    cursor.highest_contiguous_seq = 100
    snapshot = _valid_snapshot_dict(
        active_attempt_id="event-test",
        active_job_id="event-job",
        last_runtime_event_seq=200,
        latest_checkpoint_id="newer",
    )
    template = step_events()[0]
    common = dict(
        checkpoint_id="ckpt-102",
        source_operation_id=1,
        source_step_id=None,
        model_version=1,
        recovery_cursor={"epoch": 1, "next_batch_ordinal": 0},
        is_final=False,
    )
    started = dict(
        template,
        runtime_event_seq=102,
        event_type="checkpoint.started",
        details=dict(
            common,
            contract_hash="a" * 64,
            dataset_build_id="build",
            dataset_manifest_hash="b" * 64,
            parameter_manifest_hash="c" * 64,
            checkpoint_policy="periodic",
            checkpoint_policy_version=1,
            created_at=template["occurred_at"],
        ),
    )
    saved = dict(
        template,
        runtime_event_seq=103,
        event_type="checkpoint.saved",
        details=dict(
            common,
            model_path="model.bin",
            metadata_path="checkpoint.json",
            model_sha256="d" * 64,
            metadata_sha256="e" * 64,
            artifact_size_bytes=64,
            checkpoint_completed_at=template["occurred_at"],
            committed_at=template["occurred_at"],
        ),
    )

    @contextmanager
    def projection_connection():
        conn.autocommit = False
        try:
            yield conn
        finally:
            conn.rollback()
            conn.autocommit = True

    frames = []

    def capture(_attempt, frame):
        if frame["kind"] == "EVENT":
            frames.append(
                (
                    frame["runtime_event_seq"],
                    frame["payload"]["event_type"],
                    conn.info.transaction_status,
                )
            )

    monkeypatch.setattr(db, "get_connection", projection_connection)
    monkeypatch.setattr(hub, "broadcast_sync", capture)
    fail_projection = first_snapshot in ("projection_error", "commit_error")
    if fail_projection:
        # A deferred constraint fails at COMMIT; an immediate one fails during INSERT.
        timing = "DEFERRABLE INITIALLY DEFERRED" if first_snapshot == "commit_error" else ""
        conn.execute(f"CREATE TEMP TABLE failure_probe (value int UNIQUE {timing})")
        conn.execute("""
            CREATE FUNCTION pg_temp.fail_checkpoint() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN INSERT INTO pg_temp.failure_probe VALUES (1), (1); RETURN NEW; END $$
        """)
        conn.execute("""
            CREATE TRIGGER fail_projection AFTER INSERT ON pg_temp.checkpoints
            FOR EACH ROW EXECUTE FUNCTION pg_temp.fail_checkpoint()
        """)
    port.snapshot_to_return = (
        snapshot
        if fail_projection
        else (dict(snapshot, last_runtime_event_seq=first_snapshot) if first_snapshot else None)
    )
    gateway.handle_runtime_event(started)
    if first_snapshot != 200:
        assert cursor.highest_contiguous_seq == 100
        assert frames == []
        assert conn.execute("SELECT state FROM pg_temp.checkpoints").fetchall() == []
        assert conn.execute("SELECT runtime_event_seq FROM pg_temp.events").fetchall() == [(102,)]
        port.snapshot_to_return = snapshot
        if fail_projection:
            conn.execute("DROP TRIGGER fail_projection ON pg_temp.checkpoints")
        else:
            gateway.handle_runtime_event(started)

    if not fail_projection:
        assert conn.execute("SELECT state FROM pg_temp.checkpoints").fetchall() == [("WRITING",)]
        assert cursor.highest_contiguous_seq == 102
    # Even without redelivery of 102, processing 103 retries the stored checkpoint start.
    gateway.handle_runtime_event(saved)
    gateway.handle_runtime_event(started)
    assert conn.execute("SELECT state FROM pg_temp.checkpoints").fetchall() == [("COMPLETE",)]
    before = conn.execute("SELECT state, started_at FROM pg_temp.attempts").fetchone()
    port.snapshot_to_return = None
    gateway.handle_runtime_event(
        dict(
            template,
            runtime_event_seq=104,
            event_type="attempt.state_changed",
            details={"state": "RUNNING"},
        )
    )
    assert conn.execute("SELECT state, started_at FROM pg_temp.attempts").fetchone() == before
    queued = [
        dict(template, runtime_event_seq=seq, event_type="metric.sample", details={"loss": 0.1})
        for seq in range(105, 201)
    ]
    assert gateway.handle_runtime_events(queued) == len(queued)
    expected = list(range(102, 201))
    assert [seq for seq, _, _ in frames] == expected
    assert [kind for _, kind, _ in frames[:2]] == ["checkpoint.started", "checkpoint.saved"]
    assert all(status == psycopg.pq.TransactionStatus.IDLE for _, _, status in frames)
    assert conn.execute("SELECT runtime_event_seq FROM pg_temp.events ORDER BY 1").fetchall() == [
        (seq,) for seq in expected
    ]
    assert gateway.get_cursor("event-test").highest_contiguous_seq == 200
    assert gateway.get_snapshot("event-test")["latest_checkpoint_id"] == "newer"
