"""Commands API router.

GET /api/v1/commands                 — list control commands
GET /api/v1/commands/{command_id}    — get command detail
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from pbl4.management_backend import db
from pbl4.management_backend.schemas.command import CommandDetail, CommandListItem, CommandResult
from pbl4.management_backend.schemas.common import ListResponse, PageInfo
from pbl4.management_backend.services import command_service

router = APIRouter(tags=["Commands"])


@router.get(
    "/api/v1/commands",
    response_model=ListResponse[CommandListItem],
    summary="List control commands",
)
def list_commands(
    command_type: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    target_type: Annotated[str | None, Query()] = None,
    target_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[str | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = command_service.list_commands(
            conn,
            command_type=command_type,
            state=state,
            target_type=target_type,
            target_id=target_id,
            limit=limit + 1,
            cursor=cursor,
        )
    has_more = len(rows) > limit
    next_cursor = None
    if has_more:
        last = rows[limit - 1]
        next_cursor = f"{last['requested_at'].isoformat()}|{last['command_id']}"
    items = [
        CommandListItem(
            command_id=str(r["command_id"]),
            command_type=r["command_type"],
            state=r["state"],
            target_type=r["target_type"],
            target_id=str(r["target_id"]) if r.get("target_id") else None,
            requested_at=r["requested_at"],
            dispatched_at=r.get("dispatched_at"),
            completed_at=r.get("completed_at"),
        )
        for r in rows[:limit]
    ]
    return ListResponse(data=items, page=PageInfo(next_cursor=next_cursor))


@router.get(
    "/api/v1/commands/{command_id}",
    response_model=CommandDetail,
    summary="Get command detail",
)
def get_command(command_id: str):
    with db.get_connection() as conn:
        try:
            row = command_service.get_command(conn, command_id)
        except command_service.CommandNotFoundError:
            raise HTTPException(
                status_code=404, detail=f"Command '{command_id}' not found."
            ) from None

    import json

    result_jsonb = row.get("result_jsonb")
    if isinstance(result_jsonb, str):
        result_jsonb = json.loads(result_jsonb)
    result = None
    if result_jsonb:
        result = CommandResult(
            code=result_jsonb.get("code", ""),
            message=result_jsonb.get("message"),
        )

    request_jsonb = row.get("request_jsonb") or {}
    if isinstance(request_jsonb, str):
        request_jsonb = json.loads(request_jsonb)

    return CommandDetail(
        command_id=str(row["command_id"]),
        command_type=row["command_type"],
        state=row["state"],
        target_type=row["target_type"],
        target_id=str(row["target_id"]) if row.get("target_id") else None,
        request=request_jsonb,
        result=result,
        requested_at=row["requested_at"],
        dispatched_at=row.get("dispatched_at"),
        completed_at=row.get("completed_at"),
    )
