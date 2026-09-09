"""System API — health check and capabilities endpoints.

GET /api/v1/health
GET /api/v1/system/capabilities
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from pbl4.management_backend import db
from pbl4.management_backend.clients.dataset_manager import get_client as get_dm_client
from pbl4.management_backend.gateways.runtime_gateway import get_gateway
from pbl4.management_backend.schemas.common import ItemResponse
from pbl4.management_backend.schemas.runtime import (
    CapabilitiesResponse,
    FeatureFlags,
    HealthResponse,
)

router = APIRouter(tags=["System"])


@router.get(
    "/api/v1/health",
    response_model=ItemResponse[HealthResponse],
    summary="Backend health check",
)
def health() -> ItemResponse[HealthResponse]:
    """Return the liveness and connectivity status of all backend subsystems."""
    db_ok = db.check_health()
    gateway = get_gateway()
    dm_client = get_dm_client()
    dm_status = dm_client.check_health() if hasattr(dm_client, "check_health") else "unknown"

    return ItemResponse(
        data=HealthResponse(
            backend="healthy",
            postgres="healthy" if db_ok else "degraded",
            runtime_mcp="connected" if gateway.connected else "disconnected",
            dataset_manager=dm_status,
            timestamp=datetime.now(UTC),
        )
    )


@router.get(
    "/api/v1/system/capabilities",
    response_model=ItemResponse[CapabilitiesResponse],
    summary="Advertise backend capabilities",
)
def capabilities() -> ItemResponse[CapabilitiesResponse]:
    """Return backend version, protocol support, and feature flags."""
    gateway = get_gateway()
    return ItemResponse(
        data=CapabilitiesResponse(
            api_version="v1",
            dtp_versions=[1],
            mcp_versions=[1],
            runtime_connected=gateway.connected,
            runtime_instance_id=gateway.runtime_instance_id,
            supported_training_strategies=["strict_bsp"],
            feature_flags=FeatureFlags(
                attempt_websocket_stream=True,
                manual_checkpoint_request=True,
            ),
        )
    )
