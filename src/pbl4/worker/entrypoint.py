"""Console entrypoint for pbl4-worker process.

Canonical responsibility:
- Parses CLI arguments and launches the distributed training worker process.

Important boundary:
- Connects to Runtime via DTP/1; does NOT communicate directly with Management Backend.
- worker_id is assigned by Runtime; not specified via CLI flags.

Status:
- Scaffold only. Core worker loop is intentionally not implemented.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Entrypoint for pbl4-worker process."""
    parser = argparse.ArgumentParser(
        prog="pbl4-worker",
        description="PBL4 Distributed Training Worker.",
    )
    parser.add_argument(
        "--node-label",
        type=str,
        default="node-unknown",
        help="Physical/container node label for identification during registration.",
    )
    parser.add_argument(
        "--runtime-host",
        type=str,
        default="127.0.0.1",
        help="Runtime Parameter Server host.",
    )
    parser.add_argument(
        "--runtime-port",
        type=int,
        default=None,
        help="Runtime Parameter Server DTP/1 port.",
    )
    parser.parse_args()

    # Worker training loop execution is pending implementation
    print("pbl4-worker: worker implementation pending", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
