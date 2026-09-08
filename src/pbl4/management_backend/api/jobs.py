"""Jobs API router.

POST   /api/v1/jobs              — create a DRAFT job
GET    /api/v1/jobs              — list jobs
GET    /api/v1/jobs/{job_id}     — get job detail
PATCH  /api/v1/jobs/{job_id}     — update a DRAFT job
POST   /api/v1/jobs/{job_id}/validate  — validate without freezing
POST   /api/v1/jobs/{job_id}/freeze    — validate + freeze to READY
POST   /api/v1/jobs/{job_id}/start     — start a FRESH attempt
POST   /api/v1/jobs/{job_id}/retry     — retry from start
POST   /api/v1/jobs/{job_id}/resume    — resume from checkpoint
POST   /api/v1/jobs/{job_id}/clone     — clone into new DRAFT
POST   /api/v1/jobs/{job_id}/archive   — archive
"""

from __future__ import annotations

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Query, status

from pbl4.management_backend import db
from pbl4.management_backend.gateways.runtime_gateway import get_gateway
from pbl4.management_backend.schemas.common import ListResponse, PageInfo
from pbl4.management_backend.schemas.job import (
    AttemptSummary,
    JobArchiveResponse,
    JobCreateRequest,
    JobDetail,
    JobLinks,
    JobListItem,
    JobPatchRequest,
    JobResumeRequest,
    JobStartRequest,
    JobValidateResponse,
    LatestAttemptSummary,
    StartAttemptResponse,
)
from pbl4.management_backend.services import attempt_service, job_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Jobs"])


def _build_job_detail(row: dict, conn) -> JobDetail:
    rc = row.get("requested_contract") or {}
    if isinstance(rc, str):
        rc = json.loads(rc)
    res = row.get("resolved_contract")
    if isinstance(res, str):
        res = json.loads(res)

    from pbl4.management_backend.repositories import attempt_repository

    attempts = attempt_repository.list_attempts(conn, job_id=row["job_id"], limit=1)
    latest = attempts[0] if attempts else None
    attempt_count = job_service.job_repository.count_attempts(conn, row["job_id"])

    return JobDetail(
        job_id=row["job_id"],
        display_name=row["display_name"],
        description=row["description"] or "",
        state=row["state"],
        requested_contract=rc,
        resolved_contract=res,
        contract_hash=row.get("contract_hash"),
        cloned_from_job_id=row.get("cloned_from_job_id"),
        attempt_summary=AttemptSummary(
            total=attempt_count,
            latest_attempt_id=latest["attempt_id"] if latest else None,
            latest_attempt_state=latest["state"] if latest else None,
        ),
        links=JobLinks(attempts=f"/api/v1/jobs/{row['job_id']}/attempts"),
        created_at=row["created_at"],
        frozen_at=row.get("frozen_at"),
        archived_at=row.get("archived_at"),
    )


def _build_job_list_item(row: dict) -> JobListItem:
    rc = row.get("requested_contract") or {}
    if isinstance(rc, str):
        rc = json.loads(rc)
    latest_id = row.get("latest_attempt_id")
    latest_state = row.get("latest_attempt_state")
    return JobListItem(
        job_id=row["job_id"],
        display_name=row["display_name"],
        state=row["state"],
        dataset_build_id=rc.get("dataset_build_id"),
        model_id=rc.get("model_id"),
        training_strategy=rc.get("training_strategy"),
        contract_hash=row.get("contract_hash"),
        attempt_count=row.get("attempt_count", 0),
        latest_attempt=LatestAttemptSummary(attempt_id=latest_id, state=latest_state)
        if latest_id
        else None,
        created_at=row["created_at"],
        frozen_at=row.get("frozen_at"),
    )


@router.post(
    "/api/v1/jobs",
    response_model=JobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new draft job",
)
def create_job(body: JobCreateRequest):
    with db.transaction() as conn:
        row = job_service.create_job(
            conn,
            display_name=body.display_name,
            description=body.description,
            requested_contract=body.requested_contract.model_dump(),
        )
        return _build_job_detail(row, conn)


@router.get(
    "/api/v1/jobs",
    response_model=ListResponse[JobListItem],
    summary="List jobs",
)
def list_jobs(
    state: Annotated[str | None, Query(description="Filter by state")] = None,
    dataset_build_id: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(description="Free text search on name/description")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = job_service.list_jobs(
            conn,
            state=state,
            dataset_build_id=dataset_build_id,
            q=q,
            limit=limit + 1,
            cursor=cursor,
        )
    has_more = len(rows) > limit
    items = [_build_job_list_item(r) for r in rows[:limit]]
    next_cursor = None
    if has_more:
        last = rows[limit - 1]
        next_cursor = f"{last['created_at'].isoformat()}|{last['job_id']}"
    return ListResponse(data=items, page=PageInfo(next_cursor=next_cursor))


@router.get(
    "/api/v1/jobs/{job_id}",
    response_model=JobDetail,
    summary="Get job detail",
)
def get_job(job_id: str):
    with db.get_connection() as conn:
        row = job_service.get_job(conn, job_id)
        return _build_job_detail(row, conn)


@router.patch(
    "/api/v1/jobs/{job_id}",
    response_model=JobDetail,
    summary="Update a DRAFT job",
)
def patch_job(job_id: str, body: JobPatchRequest):
    with db.transaction() as conn:
        row = job_service.update_job(
            conn,
            job_id,
            display_name=body.display_name,
            description=body.description,
            requested_contract=body.requested_contract,
        )
        return _build_job_detail(row, conn)


@router.post(
    "/api/v1/jobs/{job_id}/validate",
    response_model=JobValidateResponse,
    summary="Validate job contract without freezing",
)
def validate_job(job_id: str):
    with db.get_connection() as conn:
        result = job_service.validate_job(conn, job_id)
        return JobValidateResponse(**result)


@router.post(
    "/api/v1/jobs/{job_id}/freeze",
    response_model=JobDetail,
    summary="Freeze a DRAFT job to READY state",
)
def freeze_job(job_id: str):
    with db.transaction() as conn:
        row = job_service.freeze_job(conn, job_id)
        return _build_job_detail(row, conn)


@router.post(
    "/api/v1/jobs/{job_id}/start",
    response_model=StartAttemptResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start a FRESH training attempt",
)
def start_job(job_id: str, body: JobStartRequest | None = None):
    req = body or JobStartRequest()
    with db.transaction() as conn:
        attempt_row, cmd_row = attempt_service.start_job(conn, job_id, note=req.note)

    # Fire-and-forget dispatch to runtime (best effort, command is already persisted)
    get_gateway().send_start_attempt(str(cmd_row["command_id"]), attempt_row["attempt_id"], {})

    return StartAttemptResponse(
        command_id=str(cmd_row["command_id"]),
        command_type=cmd_row["command_type"],
        command_state=cmd_row["state"],
        target_type=cmd_row["target_type"],
        target_id=str(cmd_row["target_id"]),
        job_id=job_id,
        attempt_id=attempt_row["attempt_id"],
        execution_mode=attempt_row["execution_mode"],
    )


@router.post(
    "/api/v1/jobs/{job_id}/retry",
    response_model=StartAttemptResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Retry a job from the start",
)
def retry_job(job_id: str):
    with db.transaction() as conn:
        attempt_row, cmd_row = attempt_service.retry_job(conn, job_id)

    get_gateway().send_start_attempt(str(cmd_row["command_id"]), attempt_row["attempt_id"], {})

    return StartAttemptResponse(
        command_id=str(cmd_row["command_id"]),
        command_type=cmd_row["command_type"],
        command_state=cmd_row["state"],
        target_type=cmd_row["target_type"],
        target_id=str(cmd_row["target_id"]),
        job_id=job_id,
        attempt_id=attempt_row["attempt_id"],
        execution_mode=attempt_row["execution_mode"],
    )


@router.post(
    "/api/v1/jobs/{job_id}/resume",
    response_model=StartAttemptResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Resume a job from a checkpoint",
)
def resume_job(job_id: str, body: JobResumeRequest):
    with db.transaction() as conn:
        attempt_row, cmd_row = attempt_service.resume_job(conn, job_id, body.checkpoint_id)

    get_gateway().send_start_attempt(
        str(cmd_row["command_id"]),
        attempt_row["attempt_id"],
        {"checkpoint_id": body.checkpoint_id, "execution_mode": "RESUME"},
    )

    return StartAttemptResponse(
        command_id=str(cmd_row["command_id"]),
        command_type=cmd_row["command_type"],
        command_state=cmd_row["state"],
        target_type=cmd_row["target_type"],
        target_id=str(cmd_row["target_id"]),
        job_id=job_id,
        attempt_id=attempt_row["attempt_id"],
        execution_mode=attempt_row["execution_mode"],
        resume_from_checkpoint_id=attempt_row.get("resume_from_checkpoint_id"),
    )


@router.post(
    "/api/v1/jobs/{job_id}/clone",
    response_model=JobDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Clone a job into a new DRAFT",
)
def clone_job(job_id: str):
    with db.transaction() as conn:
        row = job_service.clone_job(conn, job_id)
        return _build_job_detail(row, conn)


@router.post(
    "/api/v1/jobs/{job_id}/archive",
    response_model=JobArchiveResponse,
    summary="Archive a job",
)
def archive_job(job_id: str):
    with db.transaction() as conn:
        row = job_service.archive_job(conn, job_id)
        return JobArchiveResponse(
            job_id=row["job_id"],
            state=row["state"],
            archived_at=row["archived_at"],
        )
