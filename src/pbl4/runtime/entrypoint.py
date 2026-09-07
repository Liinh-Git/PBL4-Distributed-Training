"""Console entrypoint for pbl4-runtime process.

Canonical responsibility:
- Parses CLI arguments and launches Parameter Server and Training Coordinator.

Important boundary:
- Does NOT participate in worker-side training loop or framework execution.

Status:
- Scaffold only. Core process loop is intentionally not implemented.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Entrypoint for pbl4-runtime process."""
    parser = argparse.ArgumentParser(
        prog="pbl4-runtime",
        description="PBL4 Parameter Server and Training Coordinator.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host interface to bind.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="DTP/1 server port.",
    )
    parser.add_argument(
        "--management-port",
        type=int,
        default=None,
        help="MCP/1 management port.",
    )
    parser.parse_args()

    # Runtime Parameter Server execution is pending implementation
    print("pbl4-runtime: service implementation pending", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
