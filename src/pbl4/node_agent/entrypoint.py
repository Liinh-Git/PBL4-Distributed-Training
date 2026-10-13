"""CLI entrypoint for the PBL4 Node Agent daemon and management tool.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & User Request Phase 7.

Commands:
- `pbl4-agent start`: Start the Node Agent daemon (auto-enrolls if not already enrolled).
- `pbl4-agent status`: Inspect local node enrollment status and supervised allocations.

Security Guarantees:
- Never prints or logs node_secret or worker_join_token.
- Auto-enrolls dynamically with Management Backend during `start`.
- Status command is completely local: never connects to PostgreSQL or Backend.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from collections.abc import Sequence

from pbl4 import PACKAGE_VERSION
from pbl4.node_agent.client import NodeAgentClient
from pbl4.node_agent.config import NodeAgentConfig
from pbl4.node_agent.enrollment import EnrollmentError, enroll
from pbl4.node_agent.identity import load_identity, save_identity
from pbl4.node_agent.supervisor import (
    LOCAL_STATE_RUNNING,
    LOCAL_STATE_STARTING,
    WorkerProcessSupervisor,
)
from pbl4.node_agent.telemetry import collect_static_capabilities

logger = logging.getLogger("pbl4.node_agent")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser for pbl4-agent."""
    parser = argparse.ArgumentParser(
        prog="pbl4-agent",
        description=f"PBL4 Node Agent daemon and management tool v{PACKAGE_VERSION}",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {PACKAGE_VERSION}",
    )

    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # ─── start ────────────────────────────────────────────────────────────────
    start_parser = subparsers.add_parser(
        "start",
        help="Start the Node Agent control daemon (auto-enrolls if not already enrolled)",
    )
    start_parser.add_argument(
        "--backend-url",
        default=None,
        help="Override Backend base URL (default: $PBL4_BACKEND_URL or http://127.0.0.1:8000)",
    )
    start_parser.add_argument(
        "--var-dir",
        default=None,
        help="Node agent state directory (default: $PBL4_VAR_DIR or var/agent)",
    )
    start_parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=None,
        help="Heartbeat reporting interval in seconds (default: 5.0)",
    )
    start_parser.add_argument(
        "--telemetry-interval",
        type=float,
        default=None,
        help="Resource telemetry reporting interval in seconds (default: 10.0)",
    )
    start_parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging verbosity (default: INFO)",
    )

    # ─── status ───────────────────────────────────────────────────────────────
    status_parser = subparsers.add_parser(
        "status",
        help="Display local enrollment and supervised worker allocations",
    )
    status_parser.add_argument(
        "--var-dir",
        default=None,
        help="Node agent state directory (default: $PBL4_VAR_DIR or var/agent)",
    )

    return parser


def cmd_start(args: argparse.Namespace) -> int:
    """Execute daemon startup with automatic enrollment if not yet enrolled."""
    var_dir = args.var_dir or os.getenv("PBL4_VAR_DIR", "var/agent")
    backend_url = args.backend_url or os.getenv("PBL4_BACKEND_URL", "http://127.0.0.1:8000")

    identity = load_identity(var_dir)
    if identity is None:
        logger.info(
            "Node identity not found in '%s'. Auto-enrolling with Management Backend at %s...",
            var_dir,
            backend_url,
        )
        caps = collect_static_capabilities()
        try:
            identity = enroll(
                backend_url=backend_url,
                static_capabilities=caps,
            )
            save_identity(var_dir, identity)
            logger.info("Auto-enrollment successful! Assigned node_id: %s", identity.node_id)
        except EnrollmentError as exc:
            print("Auto-enrollment failed:", file=sys.stderr)
            if exc.code:
                print(f"code={exc.code}", file=sys.stderr)
            if exc.message:
                print(f"message={exc.message}", file=sys.stderr)
            elif not exc.code:
                print(f"{exc}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"Error: Auto-enrollment failed: {exc}", file=sys.stderr)
            return 1

    overrides: dict[str, object] = {"var_dir": var_dir, "backend_url": backend_url}
    if args.heartbeat_interval:
        overrides["heartbeat_interval_seconds"] = args.heartbeat_interval
    if args.telemetry_interval:
        overrides["telemetry_interval_seconds"] = args.telemetry_interval
    if args.log_level:
        overrides["log_level"] = args.log_level

    config = NodeAgentConfig.from_env(**overrides)

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    logger.info("Initializing WorkerProcessSupervisor for node_id='%s'...", identity.node_id)
    supervisor = WorkerProcessSupervisor(var_dir=config.var_dir, node_id=identity.node_id)

    # Reconcile surviving workers on startup
    reconciled = supervisor.reconcile_on_startup()
    active_count = sum(
        1 for r in reconciled if r.local_state in (LOCAL_STATE_STARTING, LOCAL_STATE_RUNNING)
    )
    logger.info(
        "Startup reconciliation complete: %d active worker processes surviving", active_count
    )

    client = NodeAgentClient(config=config, identity=identity, supervisor=supervisor)

    async def _async_main() -> None:
        loop = asyncio.get_running_loop()

        def _signal_handler() -> None:
            logger.info(
                "Shutdown signal received; closing agent client without stopping workers..."
            )
            client.stop()

        if os.name != "nt":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, _signal_handler)

        try:
            await client.start()
        except asyncio.CancelledError:
            pass
        finally:
            client.stop()

    try:
        asyncio.run(_async_main())
    except KeyboardInterrupt:
        logger.info("Interrupted by keyboard; client stopped.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Display local agent status and supervised allocations."""
    var_dir = args.var_dir or os.getenv("PBL4_VAR_DIR", "var/agent")
    identity = load_identity(var_dir)

    print("=" * 60)
    print("PBL4 Node Agent Status")
    print("=" * 60)
    print(f"State Directory:    {os.path.abspath(var_dir)}")

    if identity is None:
        print("Enrollment Status:  NOT ENROLLED")
        print("Hint: Host will auto-enroll automatically upon running 'pbl4-agent start'")
        return 0

    print("Enrollment Status:  ENROLLED")
    print(f"Node ID:            {identity.node_id}")

    supervisor = WorkerProcessSupervisor(var_dir=var_dir, node_id=identity.node_id)
    records = supervisor.list_records()
    active = [r for r in records if r.local_state in (LOCAL_STATE_STARTING, LOCAL_STATE_RUNNING)]

    print(f"Local Allocations:  {len(active)} active / {len(records)} total")

    if records:
        print("\nAllocations:")
        print(f"  {'Allocation ID':<36}  {'Attempt ID':<18}  {'State':<10}  {'PID':<8}")
        print("  " + "-" * 78)
        for r in records:
            pid_str = str(r.pid) if r.pid is not None else "-"
            print(f"  {r.allocation_id:<36}  {r.attempt_id:<18}  {r.local_state:<10}  {pid_str:<8}")
    print("=" * 60)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "start":
        return cmd_start(args)
    elif args.subcommand == "status":
        return cmd_status(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

