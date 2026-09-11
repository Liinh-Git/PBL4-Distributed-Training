"""Runtime API — runtime snapshot endpoint.

GET /api/v1/runtime/snapshot
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter

from pbl4.management_backend.gateways.runtime_gateway import get_gateway
from pbl4.management_backend.schemas.common import ItemResponse
from pbl4.management_backend.schemas.runtime import RuntimeSnapshot

router = APIRouter(tags=["Runtime"])


@router.get(
    "/api/v1/runtime/snapshot",
    response_model=ItemResponse[RuntimeSnapshot],
    summary="Get management-visible runtime snapshot",
)
def runtime_snapshot() -> ItemResponse[RuntimeSnapshot]:
    """Return the latest known runtime state.

    stale=true when not connected to runtime via MCP/1.
    The snapshot reflects DB projections; live data requires runtime connection.
    """
    gateway = get_gateway()
    if gateway.connected:
        with contextlib.suppress(Exception):
            state = gateway.port.request_state()
            if state:
                gateway.handle_state_snapshot(state)
    snap = gateway.get_snapshot()
    # MCP/1 represents an inactive Runtime's structurally required state objects
    # as empty objects; the public REST schema represents their absence as null.
    if snap.get("strategy_state") == {}:
        snap["strategy_state"] = None
    if snap.get("recovery_cursor") == {}:
        snap["recovery_cursor"] = None
    return ItemResponse(data=RuntimeSnapshot(**snap))
