"""Transport batching, ordered SQL projection and replay at injected boundaries."""

import copy
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from pbl4.management_backend import db
from pbl4.management_backend.gateways import redis_events
from pbl4.management_backend.gateways.mcp_port import FakeMcpClientPort
from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway
from pbl4.management_backend.repositories import attempt_repository, event_repository
from pbl4.management_backend.services import event_ingest
from pbl4.management_backend.services.event_ingest import broadcast_runtime_event
from pbl4.management_backend.websocket import hub
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.management_endpoint import _inactive_snapshot
from pbl4.runtime.process import _AttemptRunner

STREAM = "pbl4:runtime-events"


def event(seq=1):
    return {
        "attempt_id": "attempt-1",
        "job_id": "job-1",
        "runtime_event_seq": seq,
        "event_type": "metric.sample",
        "event_schema_version": 1,
        "occurred_at": "2026-10-29T00:00:00+00:00",
        "source_component": "runtime",
        "severity": "INFO",
        "details": {"loss": 0.1},
    }


@pytest.fixture
def persistence(monkeypatch):
    """Stage writes until commit, including the existing projection metadata cursor."""
    store = SimpleNamespace(
        rows={},
        watermark=0,
        watermarks={},
        projected=[],
        cursor_writes=[],
        commits=0,
        in_transaction=False,
        fault=None,
    )

    def key(attempt_id, seq):
        return seq if attempt_id == "attempt-1" else (attempt_id, seq)

    class Connection:
        def __init__(self):
            self.rollback()

        def rollback(self):
            self.rows = copy.deepcopy(store.rows)
            self.watermark = store.watermark
            self.watermarks = dict(store.watermarks)
            self.projected = list(store.projected)
            self.cursor_writes = list(store.cursor_writes)

        def commit(self):
            if store.fault == "commit" or (store.fault == "projection_commit" and self.projected):
                raise RuntimeError("injected commit failure")
            store.rows = copy.deepcopy(self.rows)
            store.watermark = self.watermark
            store.watermarks = dict(self.watermarks)
            store.projected = list(self.projected)
            store.cursor_writes = list(self.cursor_writes)
            store.commits += 1
            if store.fault == "lost_commit_reply":
                raise RuntimeError("COMMIT succeeded but its reply was lost")

    @contextmanager
    def connection():
        conn = Connection()
        store.in_transaction = True
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            store.in_transaction = False

    def insert(conn, **fields):
        seq = fields["runtime_event_seq"]
        identity = key(fields["attempt_id"], seq)
        if identity in conn.rows:
            return None
        row = {**fields, "event_id": seq, "payload_jsonb": fields.pop("payload")}
        conn.rows[identity] = row
        return row

    def read(conn, attempt_id, seq):
        if store.fault == "read":
            raise RuntimeError("injected DB read failure")
        return conn.rows.get(key(attempt_id, seq))

    def project(conn, payload):
        if store.fault == "projection" or (
            store.fault == "second_event" and payload["runtime_event_seq"] == 2
        ):
            raise RuntimeError("injected projection failure")
        conn.projected.append(payload["runtime_event_seq"])

    monkeypatch.setattr(db, "transaction", connection)
    monkeypatch.setattr(db, "get_connection", connection)
    monkeypatch.setattr(event_repository, "get_event_by_seq", read)
    monkeypatch.setattr(event_repository, "insert_event", insert)

    def attempt(conn, attempt_id):
        if store.fault == "read":
            raise RuntimeError("injected DB read failure")
        watermark = (
            conn.watermark if attempt_id == "attempt-1" else conn.watermarks.get(attempt_id, 0)
        )
        return {"state": "RUNNING", "runtime_metadata": {"highest_contiguous_seq": watermark}}

    monkeypatch.setattr(attempt_repository, "get_attempt", attempt)
    monkeypatch.setattr(attempt_repository, "get_active_attempt", lambda _: None)

    def record_cursor(conn, attempt_id, seq):
        conn.cursor_writes.append((attempt_id, seq))
        if attempt_id == "attempt-1":
            conn.watermark = seq
        else:
            conn.watermarks[attempt_id] = seq

    monkeypatch.setattr(attempt_repository, "record_event_projection_cursor", record_cursor)
    monkeypatch.setattr(RuntimeGateway, "_project_runtime_event", staticmethod(project))
    monkeypatch.setattr(
        RuntimeGateway,
        "_project_attempt_state_transition",
        staticmethod(lambda *args, **kwargs: {"state": "RUNNING"}),
    )
    monkeypatch.setattr(event_ingest, "broadcast_runtime_event", MagicMock())
    monkeypatch.setattr(hub, "broadcast_sync", MagicMock())
    return store


def consumer(monkeypatch, gateway, payload=None):
    client = MagicMock()
    fields = {"event": json.dumps(payload or event())}
    client.xreadgroup.return_value = [(STREAM, [("1-0", fields)])]
    client.xreadgroup.side_effect = lambda *args, **kwargs: (
        [] if args[2] == {STREAM: ">"} and "block" not in kwargs else client.xreadgroup.return_value
    )
    pipe = client.pipeline.return_value.__enter__.return_value
    monkeypatch.setattr(redis_events.Redis, "from_url", lambda *a, **kw: client)
    return (
        redis_events.RedisEventConsumer("redis://localhost", STREAM, gateway.handle_runtime_events),
        client,
        pipe,
    )


def gateway():
    return RuntimeGateway(FakeMcpClientPort(initially_connected=True), redis_events=True)


def entries(*payloads):
    return [(STREAM, [(f"{i}-0", {"event": json.dumps(p)}) for i, p in enumerate(payloads, 1)])]


def test_full_batch_commits_once_without_rereading_new_events(monkeypatch, persistence):
    runtime = gateway()
    instance, client, pipe = consumer(monkeypatch, runtime)
    client.xreadgroup.return_value = entries(*(event(seq) for seq in range(1, 101)))
    read = MagicMock(wraps=event_repository.get_event_by_seq)
    monkeypatch.setattr(event_repository, "get_event_by_seq", read)

    def broadcast(**payload):
        assert persistence.commits == 1
        assert persistence.watermark == 100
        assert not persistence.in_transaction

    event_ingest.broadcast_runtime_event.side_effect = broadcast
    assert instance._consume(pending=False)
    assert persistence.commits == 1
    assert persistence.projected == list(range(1, 101))
    assert persistence.cursor_writes == [("attempt-1", 100)]
    assert runtime.get_cursor("attempt-1").highest_contiguous_seq == 100
    read.assert_not_called()
    client.xreadgroup.assert_called_once()
    assert len(pipe.xack.call_args.args) == 102  # stream/group plus 100 IDs
    assert event_ingest.broadcast_runtime_event.call_count == 100


def test_failed_batch_rolls_back_every_event_then_replays(monkeypatch, persistence):
    runtime = gateway()
    instance, client, pipe = consumer(monkeypatch, runtime)
    client.xreadgroup.return_value = entries(event(1), event(2), event(3))
    persistence.fault = "second_event"
    with pytest.raises(RuntimeError, match="projection"):
        instance._consume(pending=True)
    assert persistence.rows == {}
    assert persistence.projected == []
    assert persistence.watermark == 0
    assert persistence.cursor_writes == []
    pipe.xack.assert_not_called()
    event_ingest.broadcast_runtime_event.assert_not_called()

    persistence.fault = None
    assert instance._consume(pending=True)
    assert persistence.projected == [1, 2, 3]
    assert persistence.commits == 1
    pipe.xack.assert_called_once_with(STREAM, instance.GROUP, "1-0", "2-0", "3-0")


def test_lost_commit_reply_reloads_durable_cursor_without_reprojecting(monkeypatch, persistence):
    runtime = gateway()
    instance, client, pipe = consumer(monkeypatch, runtime)
    client.xreadgroup.return_value = entries(event(1), event(2))
    persistence.fault = "lost_commit_reply"
    with pytest.raises(RuntimeError, match="reply was lost"):
        instance._consume(pending=True)
    assert persistence.watermark == 2
    assert persistence.projected == [1, 2]
    assert runtime.get_cursor("attempt-1").highest_contiguous_seq is None
    pipe.xack.assert_not_called()
    event_ingest.broadcast_runtime_event.assert_not_called()

    persistence.fault = None
    assert instance._consume(pending=True)
    assert persistence.projected == [1, 2]
    assert len(persistence.rows) == 2  # Both events remain available for WS catch-up.
    assert runtime.get_cursor("attempt-1").highest_contiguous_seq == 2
    pipe.xack.assert_called_once()


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_inside_batch_checks_payload_before_commit(monkeypatch, persistence, conflict):
    duplicate = event(1)
    if conflict:
        duplicate["details"] = {"loss": 99}
    instance, client, pipe = consumer(monkeypatch, gateway())
    client.xreadgroup.return_value = entries(event(1), duplicate, event(2))
    if conflict:
        with pytest.raises(event_ingest.ConflictingEventPayloadError):
            instance._consume(pending=True)
        assert persistence.rows == {}
        pipe.xack.assert_not_called()
        event_ingest.broadcast_runtime_event.assert_not_called()
    else:
        assert instance._consume(pending=True)
        assert persistence.projected == [1, 2]
        assert persistence.commits == 1
        assert event_ingest.broadcast_runtime_event.call_count == 2


def test_interleaved_attempts_keep_independent_batch_cursors(monkeypatch, persistence):
    runtime = gateway()
    payloads = [
        event(1),
        {**event(1), "attempt_id": "attempt-2"},
        event(2),
        {**event(2), "attempt_id": "attempt-2"},
    ]
    instance, client, _ = consumer(monkeypatch, runtime)
    client.xreadgroup.return_value = entries(*payloads)
    assert instance._consume(pending=True)
    assert len(persistence.rows) == 4
    assert persistence.commits == 1
    assert persistence.cursor_writes == [("attempt-1", 2), ("attempt-2", 2)]
    assert all(
        runtime.get_cursor(attempt).highest_contiguous_seq == 2
        for attempt in ("attempt-1", "attempt-2")
    )

    restarted, client, _ = consumer(monkeypatch, gateway())
    client.xreadgroup.return_value = entries(*payloads)
    assert restarted._consume(pending=True)
    assert len(persistence.rows) == 4
    assert event_ingest.broadcast_runtime_event.call_count == 4


@pytest.mark.parametrize("fence", ["gap", "lifecycle"])
def test_snapshot_fence_commits_prefix_before_external_io(monkeypatch, persistence, fence):
    runtime = gateway()
    snapshot = {
        **_inactive_snapshot("runtime-1"),
        "active_attempt_id": "attempt-1",
        "active_job_id": "job-1",
        "attempt_state": "RUNNING",
        "last_runtime_event_seq": 100,
    }

    def request_state():
        assert not persistence.in_transaction
        assert 1 in persistence.rows
        assert persistence.projected[:1] == [1]
        return snapshot

    monkeypatch.setattr(runtime._port, "request_state", request_state)
    middle = (
        event(3)
        if fence == "gap"
        else {**event(2), "event_type": "attempt.state_changed", "details": {"state": "RUNNING"}}
    )
    last = 4 if fence == "gap" else 3
    instance, client, pipe = consumer(monkeypatch, runtime)
    client.xreadgroup.return_value = entries(event(1), middle, event(last))
    assert instance._consume(pending=True)
    assert persistence.projected == ([1, 4] if fence == "gap" else [1, 2, 3])
    assert persistence.watermark == last
    assert runtime.get_cursor("attempt-1").highest_contiguous_seq == last
    pipe.xack.assert_called_once_with(STREAM, instance.GROUP, "1-0", "2-0", "3-0")


def test_batch_byte_limit_and_oversized_single_event(monkeypatch, persistence):
    instance, client, _ = consumer(monkeypatch, gateway())
    instance._max_batch_bytes = len(json.dumps(event()).encode())
    large = {**event(2), "details": {"message": "x" * 1000}}
    client.xreadgroup.return_value = entries(event(1), large, event(3))
    assert instance._consume(pending=True)
    assert persistence.projected == [1, 2, 3]
    assert persistence.commits == 3


def test_low_load_collects_once_then_flushes_partial_batch(monkeypatch, persistence):
    instance, client, _ = consumer(monkeypatch, gateway())
    client.xreadgroup.side_effect = [entries(event(1)), entries(event(2))]
    wait = MagicMock(return_value=False)
    monkeypatch.setattr(instance._stopping, "wait", wait)
    assert instance._consume(pending=False)
    wait.assert_called_once_with(0.025)
    assert persistence.commits == 1
    assert persistence.projected == [1, 2]
    client.xreadgroup.assert_called_with(instance.GROUP, instance.CONSUMER, {STREAM: ">"}, count=99)


def test_shutdown_keeps_unprocessed_entries_pending(monkeypatch, persistence):
    instance, _, pipe = consumer(monkeypatch, gateway())
    instance._stopping.set()
    assert not instance._consume(pending=True)
    assert persistence.rows == {}
    pipe.xack.assert_not_called()


@pytest.mark.parametrize("legacy", [False, True])
def test_contribution_event_history_preserves_legacy_and_compact_payloads(
    monkeypatch, persistence, legacy
):
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
    payload = {
        **event(),
        "event_type": "model.updated",
        "details": {
            "step_id": 0,
            "operation_id": 0,
            "input_model_version": 0,
            "output_model_version": 1,
            "total_sample_count": 64,
            "contributions": [contribution],
        },
    }
    instance, _, _ = consumer(monkeypatch, gateway(), payload)
    assert instance._consume(pending=True)
    assert persistence.rows[1]["payload_jsonb"] == payload["details"]
    assert event_ingest.broadcast_runtime_event.call_args.kwargs["payload"] == payload["details"]
    # An identical pending replay is accepted without another projection/broadcast.
    assert instance._consume(pending=True)
    assert persistence.projected == [1]
    assert event_ingest.broadcast_runtime_event.call_count == 1


def test_default_outbox_stays_bounded_at_8192_with_priority_eviction():
    outbox = EventEmitter("attempt-1", "job-1")
    for _ in range(8192):
        outbox.emit("metric.sample", {}, event()["occurred_at"])
    terminal = outbox.emit("attempt.state_changed", {"state": "COMPLETED"}, event()["occurred_at"])
    assert outbox.snapshot()["queued_event_count"] == 8192
    assert outbox.snapshot()["dropped_event_count"] == 1
    assert outbox.peek()[0].runtime_event_seq == 2
    assert outbox.peek()[-1] == terminal


def test_publish_retries_without_ack_or_mcp_and_queue_remains_bounded(monkeypatch):
    outbox = EventEmitter("", "", capacity=2)
    old = EventEmitter("old-attempt", "job-1", buffer=outbox)
    current = EventEmitter("current-attempt", "job-1", buffer=outbox)
    old.emit("metric.sample", {}, event()["occurred_at"])
    terminal = current.emit("attempt.state_changed", {"state": "COMPLETED"}, event()["occurred_at"])
    retained = old.emit("metric.sample", {}, event()["occurred_at"])
    assert old.snapshot()["dropped_event_count"] == 1
    assert outbox.snapshot()["dropped_event_count"] == 1
    assert outbox.snapshot()["queued_event_count"] == 2
    assert terminal.delivery_priority == 3
    assert outbox.ack(retained.runtime_event_seq, attempt_id="old-attempt")
    assert outbox.peek() == (terminal,)
    assert outbox.ack(terminal.runtime_event_seq, attempt_id="current-attempt")
    assert old.snapshot()["queued_event_count"] == current.snapshot()["queued_event_count"] == 0

    stopping = threading.Event()
    process = SimpleNamespace(
        _stopping=stopping,
        _manifest=None,
        _manifests={},
        _redis_url="redis://localhost",
        _redis_event_stream=STREAM,
    )
    management = MagicMock(backend_connected=False)
    runner = _AttemptRunner(process=process, payload=event(), management=management)
    runner._events = EventEmitter("attempt-1", "job-1", capacity=2)
    runner._events.emit("metric.sample", {}, event()["occurred_at"])
    client = MagicMock()
    pipe = client.pipeline.return_value.__enter__.return_value
    sent = []

    def execute():
        payloads = [json.loads(call.args[1]["event"]) for call in pipe.xadd.call_args_list]
        assert all(call.args[0] == STREAM for call in pipe.xadd.call_args_list)
        pipe.xadd.reset_mock()
        if pipe.execute.call_count == 1:
            assert runner._events.peek()[0].runtime_event_seq == payloads[0]["runtime_event_seq"]
            for _ in range(5):
                runner._events.emit("metric.sample", {}, event()["occurred_at"])
            assert runner._events.snapshot()["queued_event_count"] == 2
            assert runner._events.snapshot()["dropped_event_count"] == 4
            raise RedisConnectionError("offline")
        sent.extend(payload["runtime_event_seq"] for payload in payloads)
        if len(sent) == 2:
            stopping.set()
        return [f"{seq}-0" for seq in sent]

    pipe.execute.side_effect = execute
    monkeypatch.setattr("pbl4.runtime.redis_events.Redis.from_url", lambda *a, **kw: client)
    runner._event_thread.start()
    try:
        runner._event_thread.join(3)
        assert not runner._event_thread.is_alive()
        assert sent == [5, 6]
        assert runner._events.peek() == ()
        management.send_runtime_event.assert_not_called()
        client.close.assert_called_once()
    finally:
        stopping.set()
        runner._event_thread.join(3)


def test_partial_pipeline_write_retries_same_event_identities(monkeypatch, persistence):
    stopping = threading.Event()
    process = SimpleNamespace(
        _stopping=stopping,
        _manifest=None,
        _manifests={},
        _redis_url="redis://localhost",
        _redis_event_stream=STREAM,
    )
    management = MagicMock(backend_connected=False)
    runner = _AttemptRunner(process=process, payload=event(), management=management)
    runner._events = EventEmitter("attempt-1", "job-1")
    for _ in range(2):
        runner._events.emit("metric.sample", {}, event()["occurred_at"])
    client = MagicMock()
    pipe = client.pipeline.return_value.__enter__.return_value
    deliveries = []

    def execute():
        payloads = [json.loads(call.args[1]["event"]) for call in pipe.xadd.call_args_list]
        pipe.xadd.reset_mock()
        assert [p["runtime_event_seq"] for p in payloads] == [1, 2]
        assert runner._events.snapshot()["queued_event_count"] == 2
        if pipe.execute.call_count == 1:
            deliveries.append(payloads[0])  # Redis accepted a prefix before disconnect.
            raise RedisConnectionError("reply lost")
        deliveries.extend(payloads)
        stopping.set()
        return ["2-0", "3-0"]

    pipe.execute.side_effect = execute
    monkeypatch.setattr("pbl4.runtime.redis_events.Redis.from_url", lambda *a, **kw: client)
    runner._event_thread.start()
    try:
        runner._event_thread.join(3)
        assert not runner._event_thread.is_alive()
        assert runner._events.peek() == ()
    finally:
        stopping.set()
        runner._event_thread.join(3)
    client.pipeline.assert_called_with(transaction=False)
    management.send_runtime_event.assert_not_called()

    instance, client, _ = consumer(monkeypatch, gateway())
    client.xreadgroup.return_value = entries(*deliveries)
    assert instance._consume(pending=True)
    assert persistence.projected == [1, 2]
    assert len(persistence.rows) == 2


def test_restart_pending_replay_uses_committed_cursor_and_is_idempotent(monkeypatch, persistence):
    persistence.fault = "projection"
    first, _, pipe = consumer(monkeypatch, gateway())
    with pytest.raises(RuntimeError):
        first._consume(pending=False)
    assert len(persistence.rows) == 0  # history and projection roll back together
    assert persistence.watermark == 0
    pipe.xack.assert_not_called()

    persistence.fault = None
    restarted = gateway()
    # A fresh current-state snapshot must not suppress unprojected pending history.
    snapshot = {
        **_inactive_snapshot("runtime-1"),
        "active_attempt_id": "attempt-1",
        "active_job_id": "job-1",
        "attempt_state": "RUNNING",
        "last_runtime_event_seq": 9,
    }
    restarted.handle_state_snapshot(snapshot)
    assert restarted.get_cursor("attempt-1").highest_contiguous_seq == 0
    resumed, client, pipe = consumer(monkeypatch, restarted)
    assert resumed._consume(pending=True)
    assert persistence.projected == [1]
    assert persistence.watermark == 1
    client.xreadgroup.assert_called_with(resumed.GROUP, resumed.CONSUMER, {STREAM: "0"}, count=100)
    pipe.xack.assert_called_once_with(STREAM, resumed.GROUP, "1-0")
    pipe.xdel.assert_called_once_with(STREAM, "1-0")

    # Simulate loss of ACK response: another process replays the same entry.
    replay, _, _ = consumer(monkeypatch, gateway())
    replay._consume(pending=True)
    assert len(persistence.rows) == 1
    assert persistence.projected == [1]
    event_ingest.broadcast_runtime_event.assert_called_once()
    # MCP events are disabled in Redis mode, including accidentally duplicated delivery.
    restarted._handle_inbound_message("RUNTIME_EVENT", event(2))
    assert len(persistence.rows) == 1


def test_db_and_projection_failures_never_ack(monkeypatch, persistence):
    for failure in ("commit", "read", "projection", "projection_commit"):
        persistence.rows, persistence.projected, persistence.watermark = {}, [], 0
        persistence.fault = failure
        instance, client, pipe = consumer(monkeypatch, gateway())
        with pytest.raises(RuntimeError):
            instance._consume(pending=False)
        assert persistence.watermark == 0
        assert persistence.projected == []
        pipe.xack.assert_not_called()
        pipe.xdel.assert_not_called()
        client.xreadgroup.assert_any_call(
            instance.GROUP, instance.CONSUMER, {STREAM: ">"}, count=100, block=1000
        )

    persistence.fault = "second_event"
    instance, client, pipe = consumer(monkeypatch, gateway())
    instance._max_batch_bytes = 1  # Commit each oversized singleton before the failed successor.
    client.xreadgroup.return_value = [
        (STREAM, [(f"{seq}-0", {"event": json.dumps(event(seq))}) for seq in (1, 2, 3)])
    ]
    with pytest.raises(RuntimeError):
        instance._consume(pending=False)
    assert persistence.watermark == 1
    assert list(persistence.rows) == [1]
    assert persistence.projected == [1]
    pipe.xack.assert_called_once_with(STREAM, instance.GROUP, "1-0")
    pipe.xdel.assert_called_once_with(STREAM, "1-0")


def test_gap_snapshot_commit_and_conflicting_duplicate_remain_safe(monkeypatch, persistence):
    runtime = gateway()
    snapshot = {
        **_inactive_snapshot("runtime-1"),
        "active_attempt_id": "attempt-1",
        "active_job_id": "job-1",
        "attempt_state": "RUNNING",
        "last_runtime_event_seq": 20,
    }
    monkeypatch.setattr(runtime.port, "request_state", lambda: snapshot)
    instance, _, pipe = consumer(monkeypatch, runtime, event(3))
    instance._consume(pending=False)
    assert persistence.projected == []  # gap is fenced; snapshot reconciles current state
    assert persistence.watermark == 3
    assert runtime.get_cursor("attempt-1").gap_fenced is False
    assert any(call.args[1]["kind"] == "GAP" for call in hub.broadcast_sync.call_args_list)
    pipe.xack.assert_called_once()
    # Recovering current state at 20 must not skip queued projections 4..20.
    following, _, _ = consumer(monkeypatch, runtime, event(4))
    following._consume(pending=False)
    assert persistence.projected == [4]
    assert persistence.watermark == 4

    altered = {**event(3), "details": {"loss": 99}}
    conflicting, _, pipe = consumer(monkeypatch, runtime, altered)
    with pytest.raises(event_ingest.ConflictingEventPayloadError):
        conflicting._consume(pending=True)
    pipe.xack.assert_not_called()
    assert persistence.rows[3]["payload_jsonb"] == {"loss": 0.1}

    broadcast_runtime_event(
        attempt_id="attempt-1",
        runtime_event_seq=4,
        event_type="model.updated",
        severity="INFO",
        occurred_at=datetime(2026, 10, 29, tzinfo=UTC),
        source_component="coordinator",
        payload={"output_model_version": 12},
    )
    frame = hub.broadcast_sync.call_args.args[1]
    assert frame["payload"]["details"] == {"output_model_version": 12}
    assert frame["payload"]["event_schema_version"] == 1
    snap_frame = event_ingest.snapshot_frame(snapshot)
    assert snap_frame["runtime_event_seq"] is None
    assert snap_frame["payload"]["snapshot_seq"] == 20
    assert snap_frame["payload"]["state"]["state"] == "RUNNING"

    from pbl4.management_backend.api import attempts, events

    monkeypatch.setattr(
        attempts.attempt_service,
        "list_attempt_events",
        lambda *args, **kwargs: list(persistence.rows.values()),
    )
    monkeypatch.setattr(
        "pbl4.management_backend.gateways.runtime_gateway.get_gateway", lambda: runtime
    )
    page = attempts.list_attempt_events(
        "attempt-1",
        event_type="metric.sample",
        severity=None,
        limit=1,
        cursor=None,
        after_seq=0,
    )
    assert page.page.next_cursor == "3"  # last delivered sequence, not lookahead DB id
    assert not page.meta.gap_detected  # filtering is not a lost global event
    monkeypatch.setattr(
        events.event_ingest,
        "list_events",
        lambda *args, **kwargs: [{**persistence.rows[3], "event_id": key} for key in (10, 9, 8)],
    )
    audit = events.list_events(
        attempt_id="attempt-1",
        scope_type=None,
        scope_id=None,
        event_type=None,
        severity=None,
        limit=2,
        cursor=None,
    )
    assert [row.event_id for row in audit.data] == ["10", "9"]
    assert audit.page.next_cursor == "9"
