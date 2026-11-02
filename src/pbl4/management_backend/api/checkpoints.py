"""Checkpoints API router.

GET /api/v1/checkpoints                 — list checkpoints
GET /api/v1/checkpoints/{checkpoint_id} — get checkpoint detail
GET /api/v1/checkpoints/{checkpoint_id}/model — download model export
"""

from __future__ import annotations

import json
import logging
from contextlib import ExitStack
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from pbl4.management_backend import config, db
from pbl4.management_backend.repositories import (
    attempt_repository,
    checkpoint_repository,
    job_repository,
)
from pbl4.management_backend.schemas.checkpoint import (
    CheckpointDetail,
    CheckpointIntegrity,
    CheckpointListItem,
    CheckpointRecoveryCursor,
)
from pbl4.management_backend.schemas.common import ItemResponse, ListResponse, PageInfo
from pbl4.management_backend.services.checkpoint_artifacts import artifact_client, descriptor

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Checkpoints"])


def _row_to_list_item(row: dict) -> CheckpointListItem:
    epoch_val = row.get("epoch")
    if epoch_val is None:
        rc = row.get("recovery_cursor_jsonb")
        if isinstance(rc, str):
            try:
                rc = json.loads(rc)
            except Exception:
                rc = {}
        if isinstance(rc, dict):
            epoch_val = rc.get("epoch")

    return CheckpointListItem(
        checkpoint_id=row["checkpoint_id"],
        job_id=row.get("job_id", ""),
        created_by_attempt_id=row["created_by_attempt_id"],
        state=row["state"],
        model_version=row["model_version"],
        source_step_id=row.get("source_step_id"),
        epoch=epoch_val,
        created_at=row["created_at"],
        completed_at=row.get("completed_at"),
    )


def _row_to_detail(row: dict) -> CheckpointDetail:
    rc = row.get("recovery_cursor_jsonb") or {}
    if isinstance(rc, str):
        rc = json.loads(rc)

    cursor = None
    if rc.get("epoch") is not None:
        cursor = CheckpointRecoveryCursor(
            epoch=rc["epoch"],
            next_batch_ordinal=rc.get("next_batch_ordinal", 0),
        )

    integrity = None
    if row.get("model_sha256"):
        integrity = CheckpointIntegrity(
            model_sha256=row["model_sha256"],
            metadata_sha256=row.get("metadata_sha256"),
            artifact_size_bytes=row.get("artifact_size_bytes"),
        )

    return CheckpointDetail(
        checkpoint_id=row["checkpoint_id"],
        state=row["state"],
        job_id=row.get("job_id", ""),
        created_by_attempt_id=row["created_by_attempt_id"],
        contract_hash=row.get("contract_hash"),
        dataset_build_id=row.get("dataset_build_id"),
        dataset_manifest_hash=row.get("dataset_manifest_hash"),
        parameter_manifest_hash=row.get("parameter_manifest_hash"),
        source_operation_id=row["source_operation_id"],
        source_step_id=row.get("source_step_id"),
        model_version=row["model_version"],
        recovery_cursor=cursor,
        integrity=integrity,
        created_at=row["created_at"],
        completed_at=row.get("completed_at"),
    )


@router.get(
    "/api/v1/checkpoints",
    response_model=ListResponse[CheckpointListItem],
    summary="List checkpoints",
)
def list_checkpoints(
    attempt_id: Annotated[str | None, Query()] = None,
    job_id: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = checkpoint_repository.list_checkpoints(
            conn,
            attempt_id=attempt_id,
            job_id=job_id,
            state=state,
            limit=limit + 1,
            cursor=cursor,
        )
    has_more = len(rows) > limit
    next_cursor = None
    if has_more:
        last = rows[limit - 1]
        next_cursor = f"{last['created_at'].isoformat()}|{last['checkpoint_id']}"
    items = [_row_to_list_item(r) for r in rows[:limit]]
    return ListResponse(data=items, page=PageInfo(next_cursor=next_cursor))


@router.get(
    "/api/v1/checkpoints/{checkpoint_id}",
    response_model=ItemResponse[CheckpointDetail],
    summary="Get checkpoint detail",
)
def get_checkpoint(checkpoint_id: str):
    with db.get_connection() as conn:
        row = checkpoint_repository.get_checkpoint(conn, checkpoint_id)
        if row is None or row["artifact_retired"]:
            raise HTTPException(status_code=404, detail=f"Checkpoint '{checkpoint_id}' not found.")
        # Fetch job_id via attempt
        attempt = attempt_repository.get_attempt(conn, row["created_by_attempt_id"])
        if attempt:
            row["job_id"] = attempt["job_id"]
    return ItemResponse(data=_row_to_detail(row))


@router.get("/api/v1/checkpoints/{checkpoint_id}/model", response_class=StreamingResponse)
def download_model(checkpoint_id: str):
    """Download a verified model export from a completed checkpoint."""
    settings = config.get_settings()
    if not settings.runtime_artifact_token:
        raise HTTPException(503, "Model export is not configured")
    with db.get_connection() as conn:
        row = checkpoint_repository.get_checkpoint(conn, checkpoint_id)
        if row is None:
            raise HTTPException(404, "Checkpoint not found")
        if row["state"] != "COMPLETE" or row["artifact_retired"]:
            raise HTTPException(409, "Checkpoint artifact is unavailable")
        attempt = attempt_repository.get_attempt(conn, row["created_by_attempt_id"])
        job = job_repository.get_job(conn, attempt["job_id"])
        contract = job["resolved_contract"]
        if isinstance(contract, str):
            contract = json.loads(contract)
    stack = ExitStack()
    try:
        client = stack.enter_context(artifact_client(settings))
        response = stack.enter_context(client.export(descriptor(row), contract))
    except httpx.HTTPStatusError as exc:
        stack.close()
        status = 409 if exc.response.status_code in (404, 409) else 503
        raise HTTPException(status, "Model export is unavailable") from exc
    except (httpx.HTTPError, ValueError) as exc:
        stack.close()
        raise HTTPException(503, "Model export is unavailable") from exc

    def chunks():
        try:
            yield from response.iter_bytes(65536)
        finally:
            stack.close()

    filename = f"model-{row['model_sha256'][:12]}.zip"
    return StreamingResponse(
        chunks(),
        media_type="application/zip",
        background=BackgroundTask(stack.close),
        headers={
            "Content-Length": response.headers["Content-Length"],
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Accept-Ranges": "none",
            "Cache-Control": "no-store",
        },
    )
