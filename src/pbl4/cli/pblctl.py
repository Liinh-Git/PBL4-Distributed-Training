"""pblctl — command-line interface for managing PBL4 training.

Canonical responsibility:
- Parses CLI commands and communicates with Management Backend via REST API.
- Submits jobs, queries attempt status, and sends control signals.

Important boundary:
- Communicates exclusively with Management Backend.
- Does NOT communicate directly with Runtime or Dataset Manager.

Status:
- Scaffold only. Core command execution is intentionally not implemented.
"""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    """Console entrypoint for pblctl."""
    parser = argparse.ArgumentParser(
        prog="pblctl",
        description="PBL4 Command-Line Management Tool.",
    )
    parser.add_argument(
        "--backend-url",
        type=str,
        default=None,
        help="Management Backend REST API URL.",
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    subparsers.add_parser("status", help="Query cluster and attempt status")
    subparsers.add_parser("jobs", help="List and inspect jobs")
    subparsers.add_parser("abort", help="Abort an active attempt")
    parser.parse_args()

    print("pblctl: command execution pending backend API implementation", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
