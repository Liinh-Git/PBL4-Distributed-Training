"""Datasets API router.

POST   /api/v1/datasets                          — create dataset source
GET    /api/v1/datasets                          — list datasets
GET    /api/v1/datasets/{dataset_id}             — get dataset detail
POST   /api/v1/dataset-builds                    — create dataset build
GET    /api/v1/dataset-builds                    — list dataset builds
GET    /api/v1/dataset-builds/{id}               — get build detail
POST   /api/v1/dataset-builds/{id}/rebuild       — rebuild
POST   /api/v1/dataset-builds/{id}/deprecate     — deprecate READY build
DELETE /api/v1/dataset-builds/{id}               — delete build
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from pbl4.management_backend import db
from pbl4.management_backend.schemas.common import ListResponse, PageInfo
from pbl4.management_backend.schemas.dataset import (
    BuildCommandResponse,
    DatasetBuildCreateRequest,
    DatasetBuildDeprecateRequest,
    DatasetBuildDeprecateResponse,
    DatasetBuildDetail,
    DatasetBuildListItem,
    DatasetBuildRebuildRequest,
    DatasetCreateRequest,
    DatasetDetail,
    DatasetItem,
    ManifestSummary,
)
from pbl4.management_backend.services import dataset_service

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Datasets"])


def _build_row_to_detail(row: dict) -> DatasetBuildDetail:
    manifest_uri = row.get("manifest_uri") or ""
    hash_val = row.get("dataset_manifest_hash") or ""
    artifact_url = row.get("artifact_base_url") or ""
    manifest_summary = (
        ManifestSummary(
            dataset_manifest_hash=hash_val,
            manifest_uri=manifest_uri,
            artifact_base_url=artifact_url,
        )
        if hash_val
        else None
    )
    return DatasetBuildDetail(
        dataset_build_id=row["dataset_build_id"],
        dataset_id=row["dataset_id"],
        state=row["state"],
        current_stage=row["state"],
        progress=1.0 if row["state"] == "READY" else 0.0,
        profile=row["profile"],
        batch_size=row["batch_size"],
        shard_count=row["shard_count"],
        partition_seed=row["partition_seed"],
        sample_count=row["sample_count"],
        manifest_summary=manifest_summary,
        references=[],
        created_at=row["created_at"],
        ready_at=row.get("ready_at"),
    )


# ─── Dataset Source ───────────────────────────────────────────────────────────


@router.post(
    "/api/v1/datasets",
    response_model=DatasetDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dataset source",
)
def create_dataset(body: DatasetCreateRequest):
    with db.transaction() as conn:
        row = dataset_service.create_dataset(
            conn,
            name=body.name,
            task_type=body.task_type,
            source_type=body.source_type,
            source_reference=body.source_reference,
        )
        detail = dataset_service.get_dataset(conn, row["dataset_id"])
    return DatasetDetail(
        dataset_id=detail["dataset_id"],
        name=detail["name"],
        task_type=detail["task_type"],
        source_type=detail["source_type"],
        source_reference=detail["source_reference"],
        created_at=detail["created_at"],
        build_counts=detail["build_counts"],
    )


@router.get(
    "/api/v1/datasets",
    response_model=ListResponse[DatasetItem],
    summary="List datasets",
)
def list_datasets(
    task_type: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = dataset_service.list_datasets(
            conn, task_type=task_type, q=q, limit=limit + 1, cursor=cursor
        )
    has_more = len(rows) > limit
    items = [
        DatasetItem(
            dataset_id=r["dataset_id"],
            name=r["name"],
            task_type=r["task_type"],
            source_type=r["source_type"],
            source_reference=r["source_reference"],
            created_at=r["created_at"],
        )
        for r in rows[:limit]
    ]
    next_cursor = None
    if has_more:
        last = rows[limit - 1]
        next_cursor = f"{last['created_at'].isoformat()}|{last['dataset_id']}"
    return ListResponse(data=items, page=PageInfo(next_cursor=next_cursor))


@router.get(
    "/api/v1/datasets/{dataset_id}",
    response_model=DatasetDetail,
    summary="Get dataset detail",
)
def get_dataset(dataset_id: str):
    with db.get_connection() as conn:
        try:
            detail = dataset_service.get_dataset(conn, dataset_id)
        except dataset_service.DatasetNotFoundError:
            raise HTTPException(status_code=404, detail=f"Dataset '{dataset_id}' not found.")
    return DatasetDetail(
        dataset_id=detail["dataset_id"],
        name=detail["name"],
        task_type=detail["task_type"],
        source_type=detail["source_type"],
        source_reference=detail["source_reference"],
        created_at=detail["created_at"],
        build_counts=detail["build_counts"],
    )


# ─── Dataset Builds ──────────────────────────────────────────────────────────


@router.post(
    "/api/v1/dataset-builds",
    response_model=BuildCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a new dataset build",
)
def create_build(body: DatasetBuildCreateRequest):
    with db.transaction() as conn:
        try:
            build_row, cmd_row = dataset_service.create_build(
                conn,
                dataset_id=body.dataset_id,
                profile=body.profile,
                batch_size=body.batch_size,
                partition_seed=body.partition_seed,
                preprocessing=body.preprocessing.model_dump() if body.preprocessing else {},
            )
        except dataset_service.DatasetNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
    return BuildCommandResponse(
        command_id=str(cmd_row["command_id"]),
        command_type=cmd_row["command_type"],
        command_state=cmd_row["state"],
        target_type=cmd_row["target_type"],
        target_id=str(cmd_row["target_id"]),
        dataset_build_id=build_row["dataset_build_id"],
        dataset_build_state=build_row["state"],
    )


@router.get(
    "/api/v1/dataset-builds",
    response_model=ListResponse[DatasetBuildListItem],
    summary="List dataset builds",
)
def list_builds(
    dataset_id: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    profile: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = dataset_service.list_builds(
            conn,
            dataset_id=dataset_id,
            state=state,
            profile=profile,
            limit=limit + 1,
            cursor=cursor,
        )
    has_more = len(rows) > limit
    items = [
        DatasetBuildListItem(
            dataset_build_id=r["dataset_build_id"],
            dataset_id=r["dataset_id"],
            state=r["state"],
            profile=r["profile"],
            batch_size=r["batch_size"],
            shard_count=r["shard_count"],
            sample_count=r["sample_count"],
            created_at=r["created_at"],
            ready_at=r.get("ready_at"),
        )
        for r in rows[:limit]
    ]
    next_cursor = None
    if has_more:
        last = rows[limit - 1]
        next_cursor = f"{last['created_at'].isoformat()}|{last['dataset_build_id']}"
    return ListResponse(data=items, page=PageInfo(next_cursor=next_cursor))


@router.get(
    "/api/v1/dataset-builds/{dataset_build_id}",
    response_model=DatasetBuildDetail,
    summary="Get dataset build detail",
)
def get_build(dataset_build_id: str):
    with db.get_connection() as conn:
        try:
            row = dataset_service.get_build(conn, dataset_build_id)
        except dataset_service.DatasetBuildNotFoundError:
            raise HTTPException(status_code=404, detail=f"Build '{dataset_build_id}' not found.")
    return _build_row_to_detail(row)


@router.post(
    "/api/v1/dataset-builds/{dataset_build_id}/rebuild",
    response_model=BuildCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Rebuild a dataset build",
)
def rebuild_build(
    dataset_build_id: str, body: DatasetBuildRebuildRequest = DatasetBuildRebuildRequest()
):
    with db.transaction() as conn:
        try:
            new_build, cmd_row = dataset_service.rebuild_build(
                conn,
                dataset_build_id,
                batch_size=body.batch_size,
                partition_seed=body.partition_seed,
                preprocessing=body.preprocessing.model_dump() if body.preprocessing else None,
            )
        except dataset_service.DatasetBuildNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except dataset_service.DatasetBuildStateError as e:
            raise HTTPException(status_code=409, detail=str(e))
    return BuildCommandResponse(
        command_id=str(cmd_row["command_id"]),
        command_type=cmd_row["command_type"],
        command_state=cmd_row["state"],
        target_type=cmd_row["target_type"],
        target_id=str(cmd_row["target_id"]),
        dataset_build_id=new_build["dataset_build_id"],
        dataset_build_state=new_build["state"],
        source_dataset_build_id=dataset_build_id,
        new_dataset_build_id=new_build["dataset_build_id"],
    )


@router.post(
    "/api/v1/dataset-builds/{dataset_build_id}/deprecate",
    response_model=DatasetBuildDeprecateResponse,
    summary="Deprecate a READY dataset build",
)
def deprecate_build(
    dataset_build_id: str, body: DatasetBuildDeprecateRequest = DatasetBuildDeprecateRequest()
):
    with db.transaction() as conn:
        try:
            row = dataset_service.deprecate_build(conn, dataset_build_id)
        except dataset_service.DatasetBuildNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except dataset_service.DatasetBuildStateError as e:
            raise HTTPException(status_code=409, detail=str(e))
    return DatasetBuildDeprecateResponse(
        dataset_build_id=row["dataset_build_id"],
        state=row["state"],
        deprecated_at=row["deprecated_at"],
    )


@router.delete(
    "/api/v1/dataset-builds/{dataset_build_id}",
    response_model=BuildCommandResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Delete a dataset build",
)
def delete_build(dataset_build_id: str):
    with db.transaction() as conn:
        try:
            build_row, cmd_row = dataset_service.delete_build(conn, dataset_build_id)
        except dataset_service.DatasetBuildNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except dataset_service.DatasetBuildStateError as e:
            raise HTTPException(status_code=409, detail=str(e))
        except dataset_service.DatasetBuildReferenceError as e:
            raise HTTPException(status_code=409, detail=str(e))
    return BuildCommandResponse(
        command_id=str(cmd_row["command_id"]),
        command_type=cmd_row["command_type"],
        command_state=cmd_row["state"],
        target_type=cmd_row["target_type"],
        target_id=str(cmd_row["target_id"]),
        dataset_build_id=build_row["dataset_build_id"],
        dataset_build_state=build_row["state"],
    )
