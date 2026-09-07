#!/usr/bin/env python3
"""Local Distributed Cluster Harness — Topology Planner.

Reference: 04. Cấu trúc mã nguồn / docs/IMPLEMENTATION_CONTRACT.md

This script plans and displays the intended multi-process distributed training
cluster topology for local testing. It does NOT spawn active processes or claim
a functional cluster while core implementation is pending.

Key Architectural Invariants Demonstrated:
1. Process Boundaries: Runtime and Workers run as independent OS processes.
2. Worker Identity: Workers start with only physical/node labels (e.g. node-a, node-b, node-c).
   Logical worker_id is assigned dynamically by Runtime during registration.
   No physical node is assumed to become worker_id=0.
   No WORKER_ID environment variable is injected.
3. Network Uniformity: Whichever worker session receives logical worker_id=0 uses the
   exact same DTP/1 over TCP connection path as all other workers.

Usage:
    uv run python scripts/run_local_cluster.py --dtp-port <port> --mcp-port <port>
"""

from __future__ import annotations

import argparse


def plan_topology(
    runtime_host: str,
    dtp_port: int | None,
    mcp_port: int | None,
    node_labels: list[str],
) -> None:
    """Print the intended multi-process cluster commands and topology."""
    dtp_display = str(dtp_port) if dtp_port is not None else "<configured-dtp-port>"
    mcp_display = str(mcp_port) if mcp_port is not None else "<configured-mcp-port>"

    print("======================================================================")
    print("PBL4 LOCAL CLUSTER TOPOLOGY PLANNER")
    print("======================================================================")
    print("STATUS: Topology projection only. No processes spawned.")
    print("")
    print("Runtime (Parameter Server):")
    print(f"  Endpoint (DTP/1): {runtime_host}:{dtp_display}")
    print(f"  Management (MCP/1): {runtime_host}:{mcp_display}")
    print(
        f"  Command: uv run pbl4-runtime --host {runtime_host} "
        f"--port {dtp_display} --management-port {mcp_display}"
    )
    print("")
    print(f"Planned Workers ({len(node_labels)} nodes):")

    for label in node_labels:
        print(f"  Node [{label}]:")
        print(f"    Target Runtime DTP: {runtime_host}:{dtp_display}")
        print(f"    Initial Identity: node_label='{label}' (worker_id assigned upon registration)")
        print(
            f"    Command: uv run pbl4-worker --node-label {label} "
            f"--runtime-host {runtime_host} --runtime-port {dtp_display}"
        )
        print("    Note: Uses identical DTP/1 TCP socket path regardless of assigned logical rank.")

    print("")
    print("Process Flow:")
    print("  1. Runtime starts and opens DTP/1 TCP listening socket.")
    print("  2. Workers connect to Runtime over TCP and transmit HELLO handshake.")
    print("  3. Runtime registers sessions and assigns logical worker ranks dynamically.")
    print(
        "  4. Whichever session is assigned worker_id=0 communicates over TCP "
        "like all other workers."
    )
    print("======================================================================")


def main() -> None:
    """CLI entrypoint for local cluster planner."""
    parser = argparse.ArgumentParser(
        description="Topology planner for PBL4 local distributed cluster."
    )
    parser.add_argument(
        "--runtime-host",
        type=str,
        default="127.0.0.1",
        help="Runtime bind host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--dtp-port",
        type=int,
        default=None,
        help="Runtime DTP/1 TCP port (explicitly configured)",
    )
    parser.add_argument(
        "--mcp-port",
        type=int,
        default=None,
        help="Runtime MCP/1 management port (explicitly configured)",
    )
    parser.add_argument(
        "--nodes",
        type=str,
        nargs="+",
        default=["node-a", "node-b", "node-c"],
        help="Node labels for planned workers (default: node-a node-b node-c)",
    )
    args = parser.parse_args()

    plan_topology(
        runtime_host=args.runtime_host,
        dtp_port=args.dtp_port,
        mcp_port=args.mcp_port,
        node_labels=args.nodes,
    )


if __name__ == "__main__":
    main()
