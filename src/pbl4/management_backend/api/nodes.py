"""Node Management REST API and Control Plane WebSocket Router.

Endpoints:
- POST /api/v1/nodes/enrollment-codes  — issue one-time enrollment code
- POST /api/v1/nodes/enroll            — enroll node, consume code, issue node_secret
- GET  /api/v1/nodes                   — list registered nodes (with optional state filter)
- GET  /api/v1/nodes/{node_id}         — get detailed node inspect
- POST /api/v1/nodes/{node_id}/revoke  — revoke node credentials and disconnect active WSS
- WSS  /ws/v1/nodes/{node_id}/control  — outbound control plane channel from node agent

Invariants:
- Router coordinates requests and responses; zero direct SQL in router.
- Zero credential logging.
- Trust model matches existing Management API.
- WSS endpoint delegates to NodeControlGateway without HTTP middleware interference.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Query, WebSocket, status

from pbl4.management_backend import db
from pbl4.management_backend.gateways.node_control_gateway import get_node_control_gateway
from pbl4.management_backend.schemas.common import ItemResponse, ListResponse, PageInfo
from pbl4.management_backend.schemas.node import (
    EnrollmentCodeCreateRequest,
    EnrollmentCodeCreateResponse,
    NodeDetail,
    NodeEnrollRequest,
    NodeEnrollResponse,
    NodeItem,
)
from pbl4.management_backend.services import (
    node_enrollment_service,
    node_service,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Nodes"])


# ─── REST Endpoints ───────────────────────────────────────────────────────────


@router.post(
    "/api/v1/nodes/enrollment-codes",
    response_model=ItemResponse[EnrollmentCodeCreateResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Generate one-time node enrollment code",
)
def create_enrollment_code(body: EnrollmentCodeCreateRequest | None = None):
    """Generate a high-entropy, short-lived enrollment code.

    The code must be securely transmitted to the remote node agent operator.
    """
    req = body or EnrollmentCodeCreateRequest()
    with db.transaction() as conn:
        res = node_enrollment_service.create_enrollment_code(conn, ttl_seconds=req.ttl_seconds)
        return ItemResponse(data=EnrollmentCodeCreateResponse(**res))


@router.post(
    "/api/v1/nodes/enroll",
    response_model=ItemResponse[NodeEnrollResponse],
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a new node using a one-time enrollment code",
)
def enroll_node(body: NodeEnrollRequest):
    """Atomically consume enrollment code and issue node credentials.

    Returns the plaintext `node_secret` exactly once. Newly created node starts in OFFLINE state.
    """
    with db.transaction() as conn:
        res = node_enrollment_service.enroll_node(
            conn,
            enrollment_code=body.enrollment_code,
            display_name=body.display_name,
            capabilities=body.capabilities,
            agent_version=body.agent_version,
            platform=body.platform,
        )
        node_item = NodeItem.from_row(res["node"])
        return ItemResponse(
            data=NodeEnrollResponse(
                node_id=res["node_id"],
                node_secret=res["node_secret"],
                node=node_item,
            )
        )


@router.get(
    "/api/v1/nodes",
    response_model=ListResponse[NodeItem],
    summary="List registered nodes",
)
def list_nodes(
    state: Annotated[
        str | None, Query(description="Filter by node state: ONLINE, OFFLINE, REVOKED")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    """List cluster nodes with optional state filtering."""
    with db.get_connection() as conn:
        rows = node_service.list_nodes(conn, state=state, limit=limit)
        items = [NodeItem.from_row(r) for r in rows]
        return ListResponse(data=items, page=PageInfo(next_cursor=None))


@router.get(
    "/api/v1/nodes/{node_id}",
    response_model=ItemResponse[NodeDetail],
    summary="Get node detail",
)
def get_node(node_id: str):
    """Retrieve detailed node information, hardware capabilities, and latest telemetry."""
    with db.get_connection() as conn:
        row = node_service.get_node(conn, node_id)
        return ItemResponse(data=NodeDetail.from_row(row))


@router.post(
    "/api/v1/nodes/{node_id}/revoke",
    response_model=ItemResponse[NodeDetail],
    summary="Revoke node credentials",
)
def revoke_node(node_id: str):
    """Revoke a node's credentials permanently.

    Transitions node to REVOKED, sets credential_revoked_at, and closes active WSS connection.
    Does NOT automatically terminate running workers or abort active attempts.
    """
    gateway = get_node_control_gateway()
    with db.transaction() as conn:
        row = node_service.revoke_node(conn, node_id, gateway=gateway)

    return ItemResponse(data=NodeDetail.from_row(row))


# ─── WebSocket Endpoint ───────────────────────────────────────────────────────


@router.websocket("/ws/v1/nodes/{node_id}/control")
async def node_control_websocket(websocket: WebSocket, node_id: str):
    """Outbound control channel established from Node Agent to Management Backend."""
    gateway = get_node_control_gateway()
    await gateway.handle_websocket_connection(websocket, node_id)
