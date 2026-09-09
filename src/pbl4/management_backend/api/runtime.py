"""Runtime API — runtime snapshot endpoint.

GET /api/v1/runtime/snapshot
"""

from __future__ import annotations

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
    snap = gateway.get_snapshot()
    return ItemResponse(data=RuntimeSnapshot(**snap))
