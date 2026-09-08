"""Events API router.

GET /api/v1/events — audit log of management-plane events
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from pbl4.management_backend import db
from pbl4.management_backend.schemas.common import ListResponse, PageInfo
from pbl4.management_backend.schemas.event import EventListItem, ScopeRef
from pbl4.management_backend.services import event_ingest

router = APIRouter(tags=["Events"])


@router.get(
    "/api/v1/events",
    response_model=ListResponse[EventListItem],
    summary="List management-plane events (audit log)",
)
def list_events(
    attempt_id: Annotated[str | None, Query()] = None,
    scope_type: Annotated[str | None, Query()] = None,
    scope_id: Annotated[str | None, Query()] = None,
    event_type: Annotated[str | None, Query()] = None,
    severity: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    cursor: Annotated[str | None, Query()] = None,
):
    with db.get_connection() as conn:
        rows = event_ingest.list_events(
            conn,
            attempt_id=attempt_id,
            scope_type=scope_type,
            scope_id=scope_id,
            event_type=event_type,
            severity=severity,
            limit=limit + 1,
            cursor=cursor,
        )
    has_more = len(rows) > limit
    next_cursor = str(rows[limit]["event_id"]) if has_more else None
    items = [
        EventListItem(
            event_id=str(r["event_id"]),
            scope=ScopeRef(type=r["scope_type"], id=r.get("scope_id")),
            event_type=r["event_type"],
            severity=r["severity"],
            occurred_at=r["occurred_at"],
        )
        for r in rows[:limit]
    ]
    return ListResponse(data=items, page=PageInfo(next_cursor=next_cursor))
