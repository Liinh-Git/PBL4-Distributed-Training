"""Console entrypoint for pbl4-dataset-manager process.

Canonical responsibility:
- Parses CLI arguments and launches the Dataset Manager service.

Important boundary:
- Operates strictly in the dataset provisioning plane; does NOT launch Parameter Server.

Status:
- Scaffold only. Core process loop is intentionally not implemented.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Entrypoint for pbl4-dataset-manager process."""
    parser = argparse.ArgumentParser(
        prog="pbl4-dataset-manager",
        description="PBL4 Dataset Ingestion, Partitioning, and Serving Service.",
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

    # Dataset Manager service loop is pending implementation
    print("pbl4-dataset-manager: service implementation pending", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
