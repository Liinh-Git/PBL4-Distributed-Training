"""Training observations travel through the existing event stream after commit."""

import asyncio
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pbl4.management_backend.gateways.mcp_port import FakeMcpClientPort
from pbl4.management_backend.gateways.runtime_gateway import RuntimeGateway
from pbl4.management_backend.websocket import AttemptBroadcastHub, register_websocket_routes
from pbl4.runtime.event_emitter import EventEmitter
from tests.test_coordinator import ack, contribution, running


@pytest.fixture
def training_events(tmp_path):
    coordinator, _ = running(tmp_path)
    coordinator._events = EventEmitter("attempt", "job")
    operation = coordinator.open_step()
    for worker in range(3):
        candidate = contribution(operation, worker, loss=worker + 0.5, correct_count=0)
        _, output = coordinator.admit(candidate)
        if worker < 2:
            assert output is None  # Observability must not weaken the N/N update gate.
        if worker == 0:
            before = coordinator._events.snapshot()["last_runtime_event_seq"]
            coordinator.admit(candidate)
            assert coordinator._events.snapshot()["last_runtime_event_seq"] == before
    np.testing.assert_array_equal(output.parameters, [8.5, 18.5])
    for worker in range(3):
        coordinator.parameter_applied(ack(operation, worker))
    coordinator.commit_synchronized_step()
    return [
        {
            key: getattr(event, key)
            for key in (
                "attempt_id",
                "job_id",
                "runtime_event_seq",
                "event_type",
                "event_schema_version",
                "occurred_at",
                "source_component",
                "severity",
                "details",
            )
        }
        for event in coordinator._events.drain()
    ]


def test_runtime_reports_barrier_progress_and_measured_step_timing(training_events):
    accepted = [e for e in training_events if e["event_type"] == "gradient.accepted"]
    assert [e["details"]["strategy_state"]["accepted_contribution_count"] for e in accepted] == [
        1,
        2,
        3,
    ]
    applied = [e for e in training_events if e["event_type"] == "parameter.applied"]
    assert [e["details"]["strategy_state"]["parameter_applied_count"] for e in applied] == [1, 2, 3]
    update = next(e["details"] for e in training_events if e["event_type"] == "model.updated")
    assert [c["loss"] for c in update["contributions"]] == [0.5, 1.5, 2.5]
    committed = training_events[-1]["details"]
    assert committed["strategy_state"]["state"] == "COMMITTED"
    assert committed["strategy_state"]["synchronization_complete"] is True
    started = training_events[0]["details"]["started_at"]
    assert committed["started_at"] == started
    assert committed["update_completed_at"] == update["update_completed_at"]
    assert datetime.fromisoformat(started) <= datetime.fromisoformat(committed["committed_at"])
    assert committed["recovery_cursor"] == {"epoch": 0, "next_batch_ordinal": 1}


def gateway_with_snapshot(redis_events):
    gateway = RuntimeGateway(FakeMcpClientPort(initially_connected=True), redis_events=redis_events)
    gateway.get_cursor("attempt").highest_contiguous_seq = 0
    gateway.get_cursor("attempt").authoritative_snapshot_seq = 0
    gateway._attempt_snapshots["attempt"] = {
        "active_attempt_id": "attempt",
        "last_runtime_event_seq": 0,
        "model_version": 7,
        "workers": [{"worker_id": w, "session_id": str(w + 1)} for w in range(3)],
    }
    gateway._cached_snapshot.update(gateway._attempt_snapshots["attempt"])
    return gateway


@pytest.mark.parametrize("redis_events", [False, True])
def test_committed_events_refresh_live_state_on_both_transports(training_events, redis_events):
    gateway = gateway_with_snapshot(redis_events)
    app = FastAPI()
    register_websocket_routes(app)
    conn = MagicMock()
    rows = {
        event["runtime_event_seq"]: {
            **event,
            "payload_jsonb": event["details"],
        }
        for event in training_events
    }
    with (
        patch(
            "pbl4.management_backend.db.transaction",
            return_value=MagicMock(__enter__=lambda _: conn),
        ),
        patch(
            "pbl4.management_backend.db.get_connection",
            return_value=MagicMock(__enter__=lambda _: conn),
        ),
        patch(
            "pbl4.management_backend.services.event_ingest.ingest_runtime_event",
            return_value=MagicMock(inserted=True),
        ),
        patch(
            "pbl4.management_backend.repositories.event_repository.get_event_by_seq",
            side_effect=lambda _, __, seq: rows.get(seq),
        ),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.record_event_projection_cursor"
        ),
        patch("pbl4.management_backend.repositories.step_repository.create_step"),
        patch("pbl4.management_backend.repositories.step_repository.update_step"),
        patch("pbl4.management_backend.repositories.step_repository.upsert_worker_step"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"attempt_id": "attempt"},
        ),
        patch(
            "pbl4.management_backend.repositories.event_repository.get_latest_runtime_event_seq",
            return_value=0,
        ),
        patch("pbl4.management_backend.websocket.hub", AttemptBroadcastHub()),
        TestClient(app) as client,
        client.websocket_connect("/ws/v1/attempts/attempt?after_seq=0") as websocket,
    ):
        websocket.send_json({"kind": "PING"})
        assert websocket.receive_json() == {"kind": "PONG"}
        if redis_events:
            assert gateway.handle_runtime_events(training_events) == len(training_events)
        else:
            for event in training_events:
                gateway.handle_runtime_event(event)
        frames = [websocket.receive_json() for _ in training_events]
    assert [f["runtime_event_seq"] for f in frames] == list(rows)
    assert [f["payload"]["details"] for f in frames] == [e["details"] for e in training_events]
    snapshot = gateway.get_authoritative_snapshot("attempt")
    assert snapshot["runtime_event_seq"] == training_events[-1]["runtime_event_seq"]
    assert snapshot["authoritative_snapshot_seq"] == snapshot["runtime_event_seq"]
    assert snapshot["current_batch_ordinal"] == 1
    assert snapshot["strategy_state"]["state"] == "COMMITTED"
    assert snapshot["model_version"] == 8
    assert [w["local_model_version"] for w in snapshot["workers"]] == [8, 8, 8]
    assert gateway.get_snapshot()["current_batch_ordinal"] == 1


@pytest.mark.parametrize("redis_events", [False, True])
def test_failed_sql_does_not_publish_or_advance_live_snapshot(training_events, redis_events):
    gateway = gateway_with_snapshot(redis_events)

    @contextmanager
    def failed_commit():
        yield MagicMock()
        raise RuntimeError("COMMIT failed")

    with (
        patch("pbl4.management_backend.db.transaction", failed_commit),
        patch("pbl4.management_backend.services.event_ingest.ingest_runtime_event"),
        patch.object(gateway, "_project_runtime_event"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.record_event_projection_cursor"
        ),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as broadcast,
    ):
        if redis_events:
            with pytest.raises(RuntimeError, match="COMMIT failed"):
                gateway.handle_runtime_events(training_events)
        else:
            gateway.handle_runtime_event(training_events[0])
    broadcast.assert_not_called()
    assert gateway._attempt_snapshots["attempt"]["last_runtime_event_seq"] == 0


def test_buffered_events_do_not_regress_newer_runtime_state(training_events):
    gateway = gateway_with_snapshot(True)
    gateway._attempt_snapshots["attempt"].update(last_runtime_event_seq=100, model_version=42)
    with patch("pbl4.management_backend.websocket.hub.broadcast_sync") as broadcast:
        gateway._broadcast_projected_event(training_events[0])
    broadcast.assert_called_once()  # Still deliver history; only current state is fenced.
    assert gateway.get_authoritative_snapshot("attempt")["runtime_event_seq"] == 100
    assert gateway.get_snapshot("attempt")["model_version"] == 42


def test_websocket_delivers_event_completed_during_ping_cancellation(training_events):
    frame = {
        "kind": "EVENT",
        "attempt_id": "attempt",
        "runtime_event_seq": 1,
        "payload": {"event_type": "step.started", "details": training_events[0]["details"]},
    }

    class CompletionDuringCancel(asyncio.Queue):
        async def get(self):
            try:
                return await super().get()
            except asyncio.CancelledError:
                # Model q.get() completing just after wait() classified it as
                # pending: cancellation no longer owns the consumed event.
                return frame

    hub = AttemptBroadcastHub()
    queue = CompletionDuringCancel()
    app = FastAPI()
    register_websocket_routes(app)
    with (
        patch("pbl4.management_backend.db.get_connection"),
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt", return_value={}
        ),
        patch(
            "pbl4.management_backend.repositories.event_repository.get_latest_runtime_event_seq",
            return_value=0,
        ),
        patch("pbl4.management_backend.websocket.hub", hub),
        patch.object(hub, "subscribe", return_value=queue),
        TestClient(app) as client,
        client.websocket_connect("/ws/v1/attempts/attempt?after_seq=0") as websocket,
    ):
        websocket.send_json({"kind": "PING"})
        assert websocket.receive_json() == {"kind": "PONG"}
        # A second PING bounds the read: before the fix this returned PONG,
        # proving the first event had been consumed and silently discarded.
        websocket.send_json({"kind": "PING"})
        assert websocket.receive_json() == frame
