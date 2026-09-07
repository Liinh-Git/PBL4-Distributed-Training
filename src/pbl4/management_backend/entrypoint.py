"""Console entrypoint for pbl4-backend process.

Canonical responsibility:
- Parses CLI arguments and launches the Management Backend HTTP/WebSocket service.

Important boundary:
- Operates strictly in the management plane; does NOT launch Parameter Server or DTP/1.

Status:
- Scaffold only. Core process loop is intentionally not implemented.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Entrypoint for pbl4-backend process."""
    parser = argparse.ArgumentParser(
        prog="pbl4-backend",
        description="PBL4 Management Backend service (REST API, WebSocket, MCP/1 gateway).",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to listen on.",
    )
    parser.parse_args()

    # Core service loop is pending implementation
    print("pbl4-backend: service implementation pending", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
