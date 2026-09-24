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
import logging


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
    parser.add_argument("--cache-dir", default="var/worker-cache")
    parser.add_argument("--initialization-seed", type=int, required=True)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    if args.runtime_port is None:
        parser.error("--runtime-port is required")

    from pbl4.worker.config import WorkerConfig
    from pbl4.worker.process import WorkerProcess

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    process = WorkerProcess(
        WorkerConfig(
            node_label=args.node_label,
            runtime_host=args.runtime_host,
            runtime_port=args.runtime_port,
            cache_dir=args.cache_dir,
            heartbeat_interval_seconds=args.heartbeat_interval,
            log_level=args.log_level,
        ),
        initialization_seed=args.initialization_seed,
        device=args.device,
    )
    raise SystemExit(0 if process.run() else 1)


if __name__ == "__main__":
    main()
