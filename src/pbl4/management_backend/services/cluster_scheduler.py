"""Cluster Scheduler — pure deterministic scheduling of worker placements across cluster nodes.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md

V1 Algorithm:
1. Filter candidate nodes with state == 'ONLINE'.
2. Exclude nodes currently holding an active allocation.
3. Deterministically sort candidate nodes by node_id ascending.
4. If len(candidates) < expected_workers:
   raise NodeCapacityUnavailableError (NODE_CAPACITY_UNAVAILABLE).
5. Select exactly the first expected_workers candidate nodes.
6. For each selected node:
   - device = "cuda:0" if capabilities/telemetry indicates available NVIDIA GPU.
   - device = "cpu" otherwise.

Invariants:
- Pure business logic: ZERO SQL, ZERO repository mutation, ZERO WSS/HTTP, ZERO persistence.
- CPU/RAM/VRAM utilization is strictly telemetry in V1: never affects node selection ranking.
- No adaptive throughput, scoring, or DBS in this scheduler.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


# ─── Scheduler Exceptions ─────────────────────────────────────────────────────


class ClusterSchedulerError(Exception):
    """Base exception for cluster scheduling errors."""

    code: str = "CLUSTER_SCHEDULER_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NodeCapacityUnavailableError(ClusterSchedulerError):
    """Raised when there are insufficient available online nodes to satisfy expected_workers."""

    code: str = "NODE_CAPACITY_UNAVAILABLE"


# ─── Placement Specification ──────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class WorkerPlacementSpec:
    """Deterministic placement directive for a single worker on a target node."""

    node_id: str
    device: str


# ─── Scheduler Implementation ─────────────────────────────────────────────────


class ClusterScheduler:
    """Pure deterministic scheduler for distributed training worker placement."""

    @staticmethod
    def select_placements(
        *,
        expected_workers: int,
        nodes: list[dict[str, Any]],
        active_allocations: list[dict[str, Any]] | set[str] | None = None,
    ) -> list[WorkerPlacementSpec]:
        """Compute deterministic worker placements for a training attempt.

        Args:
            expected_workers: Number of workers required by the frozen synchronization contract.
            nodes: List of node dictionaries containing node_id, state, and capabilities_jsonb.
            active_allocations: Active allocation rows or a set of busy node ids.

        Returns:
            List of exactly expected_workers WorkerPlacementSpec objects.

        Raises:
            NodeCapacityUnavailableError: If available online nodes are fewer than expected_workers.
            ValueError: If expected_workers <= 0.
        """
        if (
            not isinstance(expected_workers, int)
            or isinstance(expected_workers, bool)
            or expected_workers <= 0
        ):
            raise ValueError(
                f"expected_workers must be a positive integer, got: {expected_workers!r}"
            )

        # Extract set of busy node IDs currently holding active allocations
        busy_node_ids: set[str] = set()
        if active_allocations:
            if isinstance(active_allocations, (set, frozenset)):
                busy_node_ids = {str(item) for item in active_allocations}
            elif isinstance(active_allocations, (list, tuple)):
                for item in active_allocations:
                    if isinstance(item, str):
                        busy_node_ids.add(item)
                    elif isinstance(item, dict) and "node_id" in item:
                        busy_node_ids.add(str(item["node_id"]))

        # 1. Filter nodes with state == 'ONLINE'
        # 2. Exclude nodes with active allocations
        candidates: list[dict[str, Any]] = []
        for node in nodes:
            state = node.get("state")
            node_id = str(node.get("node_id", ""))
            if not node_id:
                continue

            if state == "ONLINE" and node_id not in busy_node_ids:
                candidates.append(node)

        # 3. Deterministic sort by node_id ascending
        candidates.sort(key=lambda n: str(n.get("node_id", "")))

        # 4. Check available capacity
        if len(candidates) < expected_workers:
            raise NodeCapacityUnavailableError(
                "Cluster has insufficient capacity: "
                f"{expected_workers} online worker node(s) required, "
                f"but only {len(candidates)} available."
            )

        # 5. Select exactly expected_workers nodes
        selected_nodes = candidates[:expected_workers]

        # 6. Assign device based on hardware capabilities (cuda:0 vs cpu)
        placements: list[WorkerPlacementSpec] = []
        for node in selected_nodes:
            node_id = str(node["node_id"])
            device = ClusterScheduler._resolve_node_device(node)
            placements.append(WorkerPlacementSpec(node_id=node_id, device=device))

        return placements

    @staticmethod
    def _resolve_node_device(node: dict[str, Any]) -> str:
        """Inspect node capabilities to determine whether to allocate GPU or CPU.

        Telemetry metrics (CPU %, RAM, VRAM usage) do NOT influence device selection;
        only presence of valid GPU device capabilities is evaluated.
        """
        caps = node.get("capabilities_jsonb") or node.get("capabilities") or {}
        if isinstance(caps, str):
            try:
                caps = json.loads(caps)
            except Exception:
                caps = {}

        has_gpu = False
        if isinstance(caps, dict):
            gpus = caps.get("gpus")
            if (
                (isinstance(gpus, (list, tuple)) and len(gpus) > 0)
                or caps.get("gpu_count", 0) > 0
                or caps.get("has_gpu") is True
            ):
                has_gpu = True

        return "cuda:0" if has_gpu else "cpu"


# Module-level convenience function
select_placements = ClusterScheduler.select_placements
