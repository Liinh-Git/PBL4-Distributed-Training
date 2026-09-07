"""Dataset Manager — FastAPI application factory.

Canonical responsibility:
- Creates and configures the FastAPI application instance for Dataset Manager.
- Registers dataset ingestion, manifest querying, and shard download HTTP routes.

Important boundary:
- Hosts HTTP routes for dataset artifacts; does NOT host DTP/1 training protocol.

Status:
- Scaffold only.
"""

from __future__ import annotations


def create_app():  # type: ignore[no-untyped-def]
    """Create and configure the Dataset Manager FastAPI application."""
    raise NotImplementedError
