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
import logging
import signal
from pathlib import Path


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
    parser.add_argument("--dataset-manager-url", required=True)
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--parameter-manifest", required=True)
    parser.add_argument("--heartbeat-timeout", type=float, default=120.0)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    if args.port is None or args.management_port is None:
        parser.error("--port and --management-port are required")

    from pbl4.runtime.process import RuntimeProcess, load_parameter_manifest

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    process = RuntimeProcess(
        host=args.host,
        dtp_port=args.port,
        management_port=args.management_port,
        dataset_manager_url=args.dataset_manager_url,
        checkpoint_dir=Path(args.checkpoint_dir),
        parameter_manifest=load_parameter_manifest(Path(args.parameter_manifest)),
        heartbeat_timeout_seconds=args.heartbeat_timeout,
    )
    signal.signal(signal.SIGINT, lambda *_: process.stop())
    signal.signal(signal.SIGTERM, lambda *_: process.stop())
    process.run()


if __name__ == "__main__":
    main()
