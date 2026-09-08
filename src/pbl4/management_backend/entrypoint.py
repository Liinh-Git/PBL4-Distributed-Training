"""Console entrypoint for pbl4-backend process.

Canonical responsibility:
- Parses CLI arguments and launches the Management Backend HTTP/WebSocket service.

Important boundary:
- Operates strictly in the management plane; does NOT launch Parameter Server or DTP/1.
"""

from __future__ import annotations

import argparse
import logging

logger = logging.getLogger(__name__)


def main() -> None:
    """Entrypoint for pbl4-backend process."""
    import uvicorn

    parser = argparse.ArgumentParser(
        prog="pbl4-backend",
        description="PBL4 Management Backend service (REST API, WebSocket, MCP/1 gateway).",
    )
    parser.add_argument("--host", type=str, default=None, help="Host interface to bind")
    parser.add_argument("--port", type=int, default=None, help="Port to listen on")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    parser.add_argument("--log-level", type=str, default=None, help="Log level (INFO, DEBUG, ...)")

    args = parser.parse_args()

    # Load settings to resolve defaults
    from pbl4.management_backend.config import get_settings

    settings = get_settings()

    host = args.host or settings.backend_host
    port = args.port or settings.backend_port
    log_level = (args.log_level or settings.log_level).lower()

    logger.info("Starting pbl4-backend on %s:%d (log_level=%s)", host, port, log_level)

    uvicorn.run(
        "pbl4.management_backend.app:create_app",
        factory=True,
        host=host,
        port=port,
        log_level=log_level,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
