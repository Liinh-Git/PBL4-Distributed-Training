"""System API — health check and capabilities endpoints.

GET /api/v1/health
GET /api/v1/system/capabilities
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter

from management_backend import db
from management_backend.gateways.runtime_gateway import get_gateway
from management_backend.schemas.runtime import CapabilitiesResponse, FeatureFlags, HealthResponse

router = APIRouter(tags=["System"])


@router.get(
    "/api/v1/health",
    response_model=HealthResponse,
    summary="Backend health check",
)
def health() -> HealthResponse:
    """Return the liveness and connectivity status of all backend subsystems."""
    db_ok = db.check_health()
    gateway = get_gateway()

    return HealthResponse(
        backend="healthy",
        postgres="healthy" if db_ok else "degraded",
        runtime_mcp="connected" if gateway.connected else "disconnected",
        dataset_manager="unknown",  # not yet connected
        timestamp=datetime.now(timezone.utc),
    )


@router.get(
    "/api/v1/system/capabilities",
    response_model=CapabilitiesResponse,
    summary="Advertise backend capabilities",
)
def capabilities() -> CapabilitiesResponse:
    """Return backend version, protocol support, and feature flags."""
    gateway = get_gateway()
    return CapabilitiesResponse(
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
