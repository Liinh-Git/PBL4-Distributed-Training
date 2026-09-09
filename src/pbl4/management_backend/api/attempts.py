"""Attempts API router.

GET    /api/v1/attempts                              — list all attempts
GET    /api/v1/attempts/{attempt_id}                 — get attempt detail
GET    /api/v1/attempts/{attempt_id}/snapshot        — management snapshot
POST   /api/v1/attempts/{attempt_id}/abort           — abort attempt
POST   /api/v1/attempts/{attempt_id}/checkpoint-requests — request checkpoint
GET    /api/v1/attempts/{attempt_id}/join-spec       — get join spec
GET    /api/v1/attempts/{attempt_id}/workers         — list workers
GET    /api/v1/attempts/{attempt_id}/workers/{id}    — worker detail
GET    /api/v1/attempts/{attempt_id}/events          — list runtime events
GET    /api/v1/attempts/{attempt_id}/steps           — list steps
GET    /api/v1/attempts/{attempt_id}/steps/{step_id} — step detail
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Query, status

from pbl4.management_backend import db
from pbl4.management_backend.schemas.attempt import (
    AbortAttemptRequest,
    AbortAttemptResponse,
    AttemptDetail,
    AttemptLinks,
    AttemptListItem,
    AttemptSnapshot,
    CheckpointRef,
    CheckpointRequestBody,
    CheckpointRequestResponse,
    FailureInfo,
    JoinSpec,
    MembershipInfo,
    ProgressCursor,
    RuntimeInfo,
    WorkerDetail,
    WorkerSessionItem,
)
from pbl4.management_backend.schemas.common import ItemResponse, ListResponse, PageInfo
from pbl4.management_backend.schemas.event import (
    RuntimeEventItem,
    RuntimeEventsMeta,
    RuntimeEventsResponse,
)
from pbl4.management_backend.schemas.step import (
    StepDetail,
    StepListItem,
    StepTiming,
    WorkerStepItem,
)
from pbl4.management_backend.services import attempt_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Attempts"])


def _session_to_item(row: dict) -> WorkerSessionItem:
    return WorkerSessionItem(
        worker_id=row["worker_id"],
        session_id=str(row["session_id"]),
        node_label=row["node_label"],
        state=row["state"],
        protocol_version=row["protocol_version"],
        connected_at=row["connected_at"],
        last_heartbeat_at=row.get("last_heartbeat_at"),
        disconnected_at=row.get("disconnected_at"),
        failure_code=row.get("failure_code"),
    )


@router.get(
    "/api/v1/attempts",
    response_model=ListResponse[AttemptListItem],
    summary="List all attempts",
)
def list_attempts(
    job_id: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    execution_mode: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = attempt_service.list_attempts(
            conn,
            job_id=job_id,
            state=state,
            execution_mode=execution_mode,
            limit=limit + 1,
            cursor=cursor,
        )
    has_more = len(rows) > limit
    items = [
        AttemptListItem(
            attempt_id=r["attempt_id"],
            job_id=r["job_id"],
            state=r["state"],
            execution_mode=r["execution_mode"],
            created_at=r["created_at"],
            started_at=r.get("started_at"),
            ended_at=r.get("ended_at"),
            failure_code=r.get("failure_code"),
        )
        for r in rows[:limit]
    ]
    next_cursor = None
    if has_more:
        last = rows[limit - 1]
        next_cursor = f"{last['created_at'].isoformat()}|{last['attempt_id']}"
    return ListResponse(data=items, page=PageInfo(next_cursor=next_cursor))


@router.get(
    "/api/v1/attempts/{attempt_id}",
    response_model=ItemResponse[AttemptDetail],
    summary="Get attempt detail",
)
def get_attempt(attempt_id: str):
    with db.get_connection() as conn:
        row = attempt_service.get_attempt(conn, attempt_id)
        workers = attempt_service.list_attempt_workers(conn, attempt_id)
        from pbl4.management_backend.repositories import job_repository

        job = job_repository.get_job(conn, row["job_id"])
        rc = job.get("resolved_contract") if job else None
        if isinstance(rc, str):
            rc = json.loads(rc)
        try:
            expected_workers = rc["synchronization"]["expected_workers"]
            training_strategy = rc["synchronization"]["training_strategy"]
        except (KeyError, TypeError) as exc:
            raise attempt_service.AttemptStateError(
                f"Attempt '{attempt_id}' has an invalid frozen resolved contract."
            ) from exc
        if not isinstance(expected_workers, int) or isinstance(expected_workers, bool):
            raise attempt_service.AttemptStateError(
                f"Attempt '{attempt_id}' has invalid expected_workers in its frozen contract."
            )
        snap = attempt_service.get_attempt_snapshot(conn, attempt_id)

    active_sessions = [w for w in workers if w["state"] not in ("DISCONNECTED", "FAILED")]
    failure = None
    if row.get("failure_code"):
        failure = FailureInfo(code=row["failure_code"], message=row.get("failure_message"))
    progress_cursor = None
    if snap.get("epoch") is not None and snap.get("current_batch_ordinal") is not None:
        progress_cursor = ProgressCursor(
            epoch=snap["epoch"], next_batch_ordinal=snap["current_batch_ordinal"]
        )
    return ItemResponse(
        data=AttemptDetail(
            attempt_id=row["attempt_id"],
            job_id=row["job_id"],
            contract_hash=row["contract_hash"],
            state=row["state"],
            execution_mode=row["execution_mode"],
            training_strategy=training_strategy,
            expected_workers=expected_workers,
            membership=MembershipInfo(
                active_workers=len(active_sessions), expected_workers=expected_workers
            ),
            epoch=snap.get("epoch"),
            progress_cursor=progress_cursor,
            model_version=snap.get("model_version"),
            checkpoint=CheckpointRef(
                state=snap["checkpoint_state"],
                latest_checkpoint_id=snap.get("latest_checkpoint_id"),
            )
            if snap.get("checkpoint_state")
            else None,
            runtime=RuntimeInfo(
                stale=snap.get("stale", True),
                observed_at=snap.get("observed_at"),
                runtime_event_seq=snap.get("runtime_event_seq"),
            ),
            strategy_state=snap.get("strategy_state"),
            failure=failure,
            links=AttemptLinks(
                job=f"/api/v1/jobs/{row['job_id']}",
                workers=f"/api/v1/attempts/{attempt_id}/workers",
                steps=f"/api/v1/attempts/{attempt_id}/steps",
                events=f"/api/v1/attempts/{attempt_id}/events",
            ),
            created_at=row["created_at"],
            started_at=row.get("started_at"),
            ended_at=row.get("ended_at"),
        )
    )


@router.get(
    "/api/v1/attempts/{attempt_id}/snapshot",
    response_model=ItemResponse[AttemptSnapshot],
    summary="Get management-plane attempt snapshot",
)
def get_attempt_snapshot(attempt_id: str):
    with db.get_connection() as conn:
        snap = attempt_service.get_attempt_snapshot(conn, attempt_id)
    sessions = snap.get("workers", [])
    return ItemResponse(
        data=AttemptSnapshot(
            attempt_id=snap["attempt_id"],
            state=snap["state"],
            training_strategy=snap.get("training_strategy"),
            epoch=snap.get("epoch"),
            current_operation_id=snap.get("current_operation_id"),
            model_version=snap.get("model_version"),
            workers=[_session_to_item(w) for w in sessions],
            stale=snap.get("stale", True),
            observed_at=snap.get("observed_at"),
            runtime_event_seq=snap.get("runtime_event_seq"),
        )
    )


@router.post(
    "/api/v1/attempts/{attempt_id}/abort",
    response_model=ItemResponse[AbortAttemptResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Abort an active attempt",
)
def abort_attempt(
    attempt_id: str,
    body: AbortAttemptRequest | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Header 'Idempotency-Key' is required for this operation.",
            },
        )
    req = body or AbortAttemptRequest()
    cmd_row = attempt_service.execute_abort_attempt(
        db, attempt_id, reason=req.reason, idempotency_key=idempotency_key
    )

    return ItemResponse(
        data=AbortAttemptResponse(
            command_id=str(cmd_row["command_id"]),
            command_type=cmd_row["command_type"],
            command_state=cmd_row.get("command_state") or cmd_row["state"],
            target_type=cmd_row["target_type"],
            target_id=attempt_id,
            attempt_id=attempt_id,
        )
    )


@router.post(
    "/api/v1/attempts/{attempt_id}/checkpoint-requests",
    response_model=ItemResponse[CheckpointRequestResponse],
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request an out-of-schedule checkpoint",
)
def request_checkpoint(
    attempt_id: str,
    body: CheckpointRequestBody | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    if not idempotency_key:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "VALIDATION_ERROR",
                "message": "Header 'Idempotency-Key' is required for this operation.",
            },
        )
    req = body or CheckpointRequestBody()
    cmd_row = attempt_service.execute_request_checkpoint(
        db, attempt_id, reason=req.reason, idempotency_key=idempotency_key
    )

    return ItemResponse(
        data=CheckpointRequestResponse(
            command_id=str(cmd_row["command_id"]),
            command_type=cmd_row["command_type"],
            command_state=cmd_row.get("command_state") or cmd_row["state"],
            target_type=cmd_row["target_type"],
            target_id=attempt_id,
            attempt_id=attempt_id,
        )
    )


@router.get(
    "/api/v1/attempts/{attempt_id}/join-spec",
    response_model=ItemResponse[JoinSpec],
    summary="Get runtime join spec for an active attempt",
)
def get_join_spec(attempt_id: str) -> ItemResponse[JoinSpec]:
    with db.get_connection() as conn:
        spec = attempt_service.get_join_spec(conn, attempt_id)
    if spec is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "RUNTIME_UNAVAILABLE",
                "message": "Runtime not connected; join spec unavailable.",
            },
        )
    return ItemResponse(data=spec if isinstance(spec, JoinSpec) else JoinSpec(**spec))


@router.get(
    "/api/v1/attempts/{attempt_id}/workers",
    response_model=ListResponse[WorkerSessionItem],
    summary="List workers for an attempt",
)
def list_workers(attempt_id: str):
    with db.get_connection() as conn:
        workers = attempt_service.list_attempt_workers(conn, attempt_id)
    items = [_session_to_item(w) for w in workers]
    return ListResponse(data=items, page=PageInfo())


@router.get(
    "/api/v1/attempts/{attempt_id}/workers/{worker_id}",
    response_model=ItemResponse[WorkerDetail],
    summary="Get worker detail",
)
def get_worker(attempt_id: str, worker_id: int):
    with db.get_connection() as conn:
        detail = attempt_service.get_worker(conn, attempt_id, worker_id)
    active = detail.get("active_session")
    history = detail.get("historical_sessions", [])
    return ItemResponse(
        data=WorkerDetail(
            worker_id=worker_id,
            active_session=_session_to_item(active) if active else None,
            historical_sessions=[_session_to_item(h) for h in history],
        )
    )


@router.get(
    "/api/v1/attempts/{attempt_id}/events",
    response_model=RuntimeEventsResponse,
    summary="List runtime events for an attempt",
)
def list_attempt_events(
    attempt_id: str,
    event_type: Annotated[str | None, Query()] = None,
    severity: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
    after_seq: Annotated[int | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = attempt_service.list_attempt_events(
            conn,
            attempt_id,
            event_type=event_type,
            severity=severity,
            limit=limit + 1,
            cursor=cursor,
            after_seq=after_seq,
        )

    has_more = len(rows) > limit
    next_cursor = str(rows[limit]["event_id"]) if has_more else None
    page_rows = rows[:limit]
    items = [
        RuntimeEventItem(
            attempt_id=r["attempt_id"] or attempt_id,
            runtime_event_seq=r["runtime_event_seq"],
            event_type=r["event_type"],
            occurred_at=r["occurred_at"],
            source_component=r.get("source_component", "Unknown"),
            severity=r["severity"],
            details=r.get("payload_jsonb") or {},
        )
        for r in page_rows
    ]
    expected = (after_seq + 1) if after_seq is not None else 1
    gap_detected = False
    for row in page_rows:
        seq = row["runtime_event_seq"]
        if seq != expected:
            gap_detected = True
            break
        expected += 1

    from pbl4.management_backend.gateways.runtime_gateway import get_gateway

    cursor_state = get_gateway().get_cursor(attempt_id)
    gap_detected = gap_detected or cursor_state.gap_fenced
    complete = not has_more and not gap_detected
    return RuntimeEventsResponse(
        data=items,
        page=PageInfo(next_cursor=next_cursor),
        meta=RuntimeEventsMeta(
            complete=complete,
            gap_detected=gap_detected,
            snapshot_required=gap_detected,
        ),
    )


@router.get(
    "/api/v1/attempts/{attempt_id}/steps",
    response_model=ListResponse[StepListItem],
    summary="List training steps",
)
def list_steps(
    attempt_id: str,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = attempt_service.list_attempt_steps(conn, attempt_id, limit=limit + 1, cursor=cursor)

    has_more = len(rows) > limit
    next_cursor = str(rows[limit]["step_id"]) if has_more else None
    items = [
        StepListItem(
            step_id=r["step_id"],
            operation_id=r["operation_id"],
            state=r["state"],
            input_model_version=r["input_model_version"],
            output_model_version=r.get("output_model_version"),
            epoch=r["epoch"],
            batch_ordinal=r["batch_ordinal"],
            total_sample_count=r.get("total_sample_count"),
            committed_at=r.get("committed_at"),
        )
        for r in rows[:limit]
    ]
    return ListResponse(data=items, page=PageInfo(next_cursor=next_cursor))


@router.get(
    "/api/v1/attempts/{attempt_id}/steps/{step_id}",
    response_model=ItemResponse[StepDetail],
    summary="Get training step detail",
)
def get_step(attempt_id: str, step_id: int):
    with db.get_connection() as conn:
        step = attempt_service.get_step(conn, attempt_id, step_id)
    worker_steps = step.get("worker_steps", [])
    return ItemResponse(
        data=StepDetail(
            training_strategy=step["training_strategy"],
            step_id=step["step_id"],
            operation_id=step["operation_id"],
            input_model_version=step["input_model_version"],
            output_model_version=step.get("output_model_version"),
            state=step["state"],
            epoch=step["epoch"],
            batch_ordinal=step["batch_ordinal"],
            total_sample_count=step.get("total_sample_count"),
            timing=StepTiming(
                started_at=step["started_at"],
                update_completed_at=step.get("update_completed_at"),
                synchronization_completed_at=step.get("synchronization_completed_at"),
                committed_at=step.get("committed_at"),
            )
            if step.get("started_at")
            else None,
            worker_steps=[
                WorkerStepItem(
                    worker_id=ws["worker_id"],
                    session_id=str(ws["session_id"]),
                    shard_id=ws["shard_id"],
                    batch_id=ws["batch_id"],
                    sample_count=ws["sample_count"],
                )
                for ws in worker_steps
            ],
        )
    )
