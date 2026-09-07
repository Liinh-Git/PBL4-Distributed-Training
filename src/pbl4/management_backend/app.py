"""Management Backend — FastAPI application factory.

Canonical responsibility:
- Creates and configures the FastAPI application instance for Management Backend.
- Registers API routers, middleware, and dependency providers.

Important boundary:
- Hosts management REST API and WebSocket routes; does not host DTP/1 training endpoints.

Status:
- Scaffold only.
"""

from __future__ import annotations


def create_app():  # type: ignore[no-untyped-def]
    """Create and configure the Management Backend FastAPI application."""
    raise NotImplementedError
