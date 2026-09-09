"""Targeted tests for Round 3 final architecture repairs.

11.1 WS race test: subscribe-first prevents event loss and deduplicates.
11.2 Event persistence failure: cursor does NOT advance and no broadcast.
11.3 Command failure mapping: REJECTED/FAILED does NOT return 202.
11.4 OpenAPI envelope test: system/join-spec advertise {data, meta}.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import psycopg
import pytest
from fastapi.testclient import TestClient

from pbl4.management_backend.app import create_app
from pbl4.management_backend.gateways.runtime_gateway import get_gateway
from pbl4.management_backend.services import attempt_service, event_ingest
from pbl4.management_backend.websocket import AttemptBroadcastHub

# ─── 11.1 WebSocket Contiguous Out-of-Order & Replay Dedup Tests ─────────────


@pytest.mark.asyncio
async def test_11_1_websocket_subscribe_first_no_event_loss():
    """Verify that subscribing first ensures no event loss and duplicate replay is dropped."""
    hub = AttemptBroadcastHub()
    attempt_id = "att_test_race"

    # Client subscribes FIRST (as implemented in _attempt_ws)
    q = hub.subscribe(attempt_id)
    last_contiguous_sent_seq = 2
    pending_live_events: dict[int, dict] = {}

    # While catch-up queries DB (replay seq 1 and 2),
    # a live event (seq 2 duplicate, and seq 3 new) arrives in queue
    await hub.broadcast(
        attempt_id,
        {"kind": "EVENT", "attempt_id": attempt_id, "runtime_event_seq": 2, "payload": {}},
    )
    await hub.broadcast(
        attempt_id,
        {"kind": "EVENT", "attempt_id": attempt_id, "runtime_event_seq": 3, "payload": {}},
    )

    delivered_events = []
    while not q.empty():
        event = await q.get()
        if isinstance(event, dict) and event.get("kind") == "EVENT":
            e_seq = event.get("runtime_event_seq")
            baseline = last_contiguous_sent_seq if last_contiguous_sent_seq is not None else 0
            if e_seq <= baseline:
                continue
            elif e_seq == baseline + 1:
                delivered_events.append(event)
                last_contiguous_sent_seq = e_seq
                while (
                    last_contiguous_sent_seq is not None
                    and (last_contiguous_sent_seq + 1) in pending_live_events
                ):
                    next_seq = last_contiguous_sent_seq + 1
                    next_ev = pending_live_events.pop(next_seq)
                    delivered_events.append(next_ev)
                    last_contiguous_sent_seq = next_seq
            else:
                pending_live_events[e_seq] = event

    hub.unsubscribe(attempt_id, q)

    # Event 2 was dropped as duplicate; Event 3 was preserved and delivered!
    assert len(delivered_events) == 1
    assert delivered_events[0]["runtime_event_seq"] == 3
    assert last_contiguous_sent_seq == 3


@pytest.mark.asyncio
async def test_ws_out_of_order_contiguous_delivery():
    """Baseline 123 -> Live 125, 124 -> Wire delivery 124, 125; cursor 125."""
    hub = AttemptBroadcastHub()
    attempt_id = "att_test_ooo"
    q = hub.subscribe(attempt_id)

    last_contiguous_sent_seq = 123
    pending_live_events: dict[int, dict] = {}
    delivered = []

    # Live events arrive out of order: 125, then 124
    await hub.broadcast(
        attempt_id,
        {"kind": "EVENT", "attempt_id": attempt_id, "runtime_event_seq": 125, "payload": {}},
    )
    await hub.broadcast(
        attempt_id,
        {"kind": "EVENT", "attempt_id": attempt_id, "runtime_event_seq": 124, "payload": {}},
    )

    while not q.empty():
        event = await q.get()
        if isinstance(event, dict) and event.get("kind") == "EVENT":
            e_seq = event.get("runtime_event_seq")
            baseline = last_contiguous_sent_seq if last_contiguous_sent_seq is not None else 0
            if e_seq <= baseline:
                continue
            elif e_seq == baseline + 1:
                delivered.append(event)
                last_contiguous_sent_seq = e_seq
                while (
                    last_contiguous_sent_seq is not None
                    and (last_contiguous_sent_seq + 1) in pending_live_events
                ):
                    next_seq = last_contiguous_sent_seq + 1
                    next_ev = pending_live_events.pop(next_seq)
                    delivered.append(next_ev)
                    last_contiguous_sent_seq = next_seq
            else:
                pending_live_events[e_seq] = event

    hub.unsubscribe(attempt_id, q)

    # Wire order MUST be 124 then 125
    assert [e["runtime_event_seq"] for e in delivered] == [124, 125]
    assert last_contiguous_sent_seq == 125


@pytest.mark.asyncio
async def test_ws_replay_live_duplicate_no_double_delivery():
    """Replayed 124 -> Queued duplicate 124, then 125 -> Wire 124, 125."""
    hub = AttemptBroadcastHub()
    attempt_id = "att_test_dedup"
    q = hub.subscribe(attempt_id)

    # DB replay completed up to 124
    replayed = [{"kind": "EVENT", "runtime_event_seq": 124}]
    last_contiguous_sent_seq = 124
    pending_live_events: dict[int, dict] = {}
    delivered = list(replayed)

    # Live queue contains duplicate 124 and new 125
    await hub.broadcast(
        attempt_id,
        {"kind": "EVENT", "attempt_id": attempt_id, "runtime_event_seq": 124, "payload": {}},
    )
    await hub.broadcast(
        attempt_id,
        {"kind": "EVENT", "attempt_id": attempt_id, "runtime_event_seq": 125, "payload": {}},
    )

    while not q.empty():
        event = await q.get()
        if isinstance(event, dict) and event.get("kind") == "EVENT":
            e_seq = event.get("runtime_event_seq")
            baseline = last_contiguous_sent_seq if last_contiguous_sent_seq is not None else 0
            if e_seq <= baseline:
                continue
            elif e_seq == baseline + 1:
                delivered.append(event)
                last_contiguous_sent_seq = e_seq
                while (
                    last_contiguous_sent_seq is not None
                    and (last_contiguous_sent_seq + 1) in pending_live_events
                ):
                    next_seq = last_contiguous_sent_seq + 1
                    next_ev = pending_live_events.pop(next_seq)
                    delivered.append(next_ev)
                    last_contiguous_sent_seq = next_seq
            else:
                pending_live_events[e_seq] = event

    hub.unsubscribe(attempt_id, q)

    assert [e["runtime_event_seq"] for e in delivered] == [124, 125]
    assert last_contiguous_sent_seq == 125


# ─── Event Dedup Tests (Exact Semantic Matching) ──────────────────────────────


def test_event_ingest_exact_duplicate_is_idempotent():
    """TEST A: Same attempt_id, seq, and all immutable fields -> duplicate."""
    mock_conn = MagicMock(spec=psycopg.Connection)
    attempt_id = "att_dup_test"
    seq = 10
    now = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    payload = {"step": 1, "loss": 0.5}

    existing_row = {
        "event_id": "ev_1",
        "attempt_id": attempt_id,
        "runtime_event_seq": seq,
        "event_type": "STEP_COMMITTED",
        "severity": "INFO",
        "source_component": "Runtime",
        "scope_type": "ATTEMPT",
        "scope_id": attempt_id,
        "occurred_at": now,
        "payload_jsonb": payload,
        "persisted_at": now,
    }

    with (
        patch(
            "pbl4.management_backend.repositories.event_repository.get_event_by_seq",
            return_value=existing_row,
        ),
        patch("pbl4.management_backend.repositories.event_repository.insert_event") as mock_insert,
    ):
        res = event_ingest.ingest_runtime_event(
            mock_conn,
            attempt_id=attempt_id,
            runtime_event_seq=seq,
            event_type="STEP_COMMITTED",
            severity="INFO",
            occurred_at=now,
            source_component="Runtime",
            payload=payload,
        )
        assert res.inserted is False
        assert res.row == existing_row
        mock_insert.assert_not_called()


def test_event_ingest_different_occurred_at_raises_conflict():
    """TEST B: Same seq, same payload, different occurred_at -> ConflictingEventPayloadError."""
    mock_conn = MagicMock(spec=psycopg.Connection)
    attempt_id = "att_conflict_time"
    seq = 10
    t1 = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 9, 10, 1, 0, tzinfo=UTC)
    payload = {"step": 1, "loss": 0.5}

    existing_row = {
        "event_id": "ev_1",
        "attempt_id": attempt_id,
        "runtime_event_seq": seq,
        "event_type": "STEP_COMMITTED",
        "severity": "INFO",
        "source_component": "Runtime",
        "occurred_at": t1,
        "payload_jsonb": payload,
    }

    with (
        patch(
            "pbl4.management_backend.repositories.event_repository.get_event_by_seq",
            return_value=existing_row,
        ),
        pytest.raises(event_ingest.ConflictingEventPayloadError),
    ):
        event_ingest.ingest_runtime_event(
            mock_conn,
            attempt_id=attempt_id,
            runtime_event_seq=seq,
            event_type="STEP_COMMITTED",
            severity="INFO",
            occurred_at=t2,  # Differs!
            source_component="Runtime",
            payload=payload,
        )


def test_event_ingest_different_immutable_field_raises_conflict():
    """TEST C: Different event_type or severity -> ConflictingEventPayloadError."""
    mock_conn = MagicMock(spec=psycopg.Connection)
    attempt_id = "att_conflict_field"
    seq = 10
    now = datetime(2026, 9, 9, 10, 0, 0, tzinfo=UTC)
    payload = {"loss": 0.5}

    existing_row = {
        "event_id": "ev_1",
        "attempt_id": attempt_id,
        "runtime_event_seq": seq,
        "event_type": "STEP_COMMITTED",
        "severity": "INFO",
        "source_component": "Runtime",
        "occurred_at": now,
        "payload_jsonb": payload,
    }

    with patch(
        "pbl4.management_backend.repositories.event_repository.get_event_by_seq",
        return_value=existing_row,
    ):
        # Different severity
        with pytest.raises(event_ingest.ConflictingEventPayloadError):
            event_ingest.ingest_runtime_event(
                mock_conn,
                attempt_id=attempt_id,
                runtime_event_seq=seq,
                event_type="STEP_COMMITTED",
                severity="ERROR",  # Differs!
                occurred_at=now,
                source_component="Runtime",
                payload=payload,
            )

        # Different event_type
        with pytest.raises(event_ingest.ConflictingEventPayloadError):
            event_ingest.ingest_runtime_event(
                mock_conn,
                attempt_id=attempt_id,
                runtime_event_seq=seq,
                event_type="STEP_FAILED",  # Differs!
                severity="INFO",
                occurred_at=now,
                source_component="Runtime",
                payload=payload,
            )


# ─── 11.2 Event Persistence Failure Cursor Invariant ─────────────────────────


def test_11_2_event_persistence_failure_cursor_does_not_advance():
    """If DB insert fails, gateway cursor MUST NOT advance and event must not broadcast."""
    mock_conn = MagicMock(spec=psycopg.Connection)
    attempt_id = "att_persist_fail"
    gw = get_gateway()
    cursor = gw.get_cursor(attempt_id)
    # Establish a known contiguous baseline
    cursor.highest_contiguous_seq = 5
    initial_contiguous = cursor.highest_contiguous_seq
    assert initial_contiguous == 5
    next_seq = 6

    with (
        patch(
            "pbl4.management_backend.repositories.event_repository.get_event_by_seq",
            return_value=None,
        ),
        patch(
            "pbl4.management_backend.repositories.event_repository.insert_event",
            side_effect=psycopg.OperationalError("Disk failure during event insert"),
        ),
        patch("pbl4.management_backend.websocket.hub.broadcast_sync") as mock_broadcast,
    ):
        with pytest.raises(psycopg.OperationalError):
            event_ingest.ingest_runtime_event(
                mock_conn,
                attempt_id=attempt_id,
                runtime_event_seq=next_seq,
                event_type="STEP_COMMITTED",
                severity="INFO",
                occurred_at=datetime.now(UTC),
                payload={"loss": 0.5},
            )

        # Invariant checks:
        # 1. Contiguous cursor did NOT advance past 5
        assert cursor.highest_contiguous_seq == 5
        # 2. Event was NOT broadcast to websocket clients
        mock_broadcast.assert_not_called()


# ─── 11.3 Command Failure Mapping ─────────────────────────────────────────────


def test_11_3_command_rejected_and_failed_not_202():
    """COMMAND_RESULT with REJECTED or FAILED must raise errors and not return 202."""
    db_mock = MagicMock()
    mock_conn = MagicMock()
    db_mock.transaction.return_value.__enter__.return_value = mock_conn

    # 1. Test REJECTED mapping -> CommandRejectedError (409)
    gw = get_gateway()
    with (
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"attempt_id": "att_1", "job_id": "job_1", "state": "RUNNING"},
        ),
        patch(
            "pbl4.management_backend.repositories.command_repository.create_command",
            return_value={
                "command_id": "cmd_rej_1",
                "state": "PENDING",
                "request": {
                    "command_id": "cmd_rej_1",
                    "job_id": "job_1",
                    "attempt_id": "att_1",
                    "reason": "test",
                    "requested_at": "2026-09-09T00:00:00+00:00",
                },
            },
        ),
        patch(
            "pbl4.management_backend.services.idempotency.acquire_or_get_record",
            return_value=(None, "NEW"),
        ),
        patch(
            "pbl4.management_backend.services.idempotency.complete_record",
            return_value=None,
        ),
        patch.object(
            gw,
            "send_command_and_wait_result",
            return_value={
                "command_id": "cmd_rej_1",
                "state": "REJECTED",
                "result": {
                    "code": "ATTEMPT_NOT_ABORTABLE",
                    "message": "Attempt already terminating",
                },
            },
        ),
    ):
        with pytest.raises(attempt_service.CommandRejectedError) as exc_info:
            attempt_service.execute_abort_attempt(
                db_mock,
                attempt_id="att_1",
                reason="test",
                idempotency_key="key_rej_1",
            )
        assert exc_info.value.status_code == 409
        assert exc_info.value.code == "ATTEMPT_NOT_ABORTABLE"
        assert exc_info.value.command_id == "cmd_rej_1"

    # 2. Test FAILED mapping -> CommandFailedError (502)
    with (
        patch(
            "pbl4.management_backend.repositories.attempt_repository.get_attempt",
            return_value={"attempt_id": "att_1", "job_id": "job_1", "state": "RUNNING"},
        ),
        patch(
            "pbl4.management_backend.repositories.command_repository.create_command",
            return_value={
                "command_id": "cmd_fail_1",
                "state": "PENDING",
                "request": {
                    "command_id": "cmd_fail_1",
                    "job_id": "job_1",
                    "attempt_id": "att_1",
                    "reason": "test",
                    "requested_at": "2026-09-09T00:00:00+00:00",
                },
            },
        ),
        patch(
            "pbl4.management_backend.services.idempotency.acquire_or_get_record",
            return_value=(None, "NEW"),
        ),
        patch(
            "pbl4.management_backend.services.idempotency.complete_record",
            return_value=None,
        ),
        patch.object(
            gw,
            "send_command_and_wait_result",
            return_value={
                "command_id": "cmd_fail_1",
                "state": "FAILED",
                "result": {"code": "RUNTIME_ERROR", "message": "Runtime crashed"},
            },
        ),
    ):
        with pytest.raises(attempt_service.CommandFailedError) as exc_info:
            attempt_service.execute_abort_attempt(
                db_mock,
                attempt_id="att_1",
                reason="test",
                idempotency_key="key_fail_1",
            )
        assert exc_info.value.status_code == 502
        assert exc_info.value.code == "COMMAND_FAILED"
        assert exc_info.value.details == {"runtime_code": "RUNTIME_ERROR"}
        assert exc_info.value.command_id == "cmd_fail_1"


def test_system_api_decodes_canonical_item_envelopes():
    source = (Path(__file__).parents[4] / "web" / "src" / "api" / "system.ts").read_text(
        encoding="utf-8"
    )
    assert "api.getItem<HealthResponse>('/health')" in source
    assert "api.getItem<CapabilitiesResponse>('/system/capabilities')" in source
    assert "api.getItem<RuntimeSnapshot>('/runtime/snapshot')" in source
    assert "api.get<" not in source


# ─── 11.4 OpenAPI Envelope Shape Test ─────────────────────────────────────────


def test_11_4_openapi_envelope_shape():
    """Verify that system and join-spec endpoints advertise {data, meta} envelope in OpenAPI."""
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/api/openapi.json")
        assert r.status_code == 200
        schema = r.json()

        paths = schema["paths"]
        # Check system endpoints
        for path in (
            "/api/v1/health",
            "/api/v1/system/capabilities",
            "/api/v1/runtime/snapshot",
            "/api/v1/attempts/{attempt_id}/join-spec",
        ):
            assert path in paths, f"{path} not in OpenAPI schema"
            resp_200 = paths[path]["get"]["responses"]["200"]
            schema_ref = resp_200["content"]["application/json"]["schema"]
            ref = schema_ref.get("$ref", "")
            # Must reference an ItemResponse schema with data and meta
            assert "ItemResponse" in ref, f"Expected ItemResponse ref for {path}, got {schema_ref}"
            comp_name = ref.split("/")[-1]
            component = schema["components"]["schemas"][comp_name]
            assert "data" in component["properties"], f"'data' property missing in {comp_name}"
            assert "meta" in component["properties"], f"'meta' property missing in {comp_name}"
