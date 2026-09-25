"""System API — health check and capabilities endpoints.

GET /api/v1/health
GET /api/v1/system/capabilities
"""

from __future__ import annotations

import logging
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
    SupportedModel,
)
from pbl4.management_backend.services import model_catalog

logger = logging.getLogger(__name__)

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
    try:
        dm_status = dm_client.check_health() if hasattr(dm_client, "check_health") else "unknown"
    except Exception as exc:
        logger.warning("Dataset Manager health probe failed with unexpected error: %s", exc)
        dm_status = "unreachable"

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
    models = [
        SupportedModel(
            model_id=str(m["model_id"]),
            display_name=str(m["display_name"]),
            task_type=(
                str(m["supported_tasks"][0]) if m.get("supported_tasks") else "image_classification"
            ),
        )
        for m in model_catalog.list_models()
    ]
    return ItemResponse(
        data=CapabilitiesResponse(
            api_version="v1",
            dtp_versions=[1],
            mcp_versions=[1],
            runtime_connected=gateway.connected,
            runtime_instance_id=gateway.runtime_instance_id,
            supported_training_strategies=["strict_bsp"],
            supported_models=models,
            feature_flags=FeatureFlags(
                attempt_websocket_stream=True,
                manual_checkpoint_request=True,
            ),
        )
    )
