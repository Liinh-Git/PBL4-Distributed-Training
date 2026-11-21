"""Cluster Scheduler — management-only random/manual placement across idle ONLINE Nodes.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md

V1 Algorithm:
1. Filter candidate nodes with state == 'ONLINE'.
2. Exclude nodes currently holding an active allocation.
3. First start: choose up to AUTO_WORKER_LIMIT randomly, or 1..MANUAL_WORKER_LIMIT manually.
4. Frozen Job: require exactly expected_workers; above the automatic cap requires manual Nodes.
5. Sort the selected placements by node_id for stable dispatch order.
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
import random
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

AUTO_WORKER_LIMIT = 3
MANUAL_WORKER_LIMIT = 5


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
    """Pure placement selection; allocations persist each randomized choice exactly once."""

    @staticmethod
    def select_placements(
        *,
        expected_workers: int | None = None,
        nodes: list[dict[str, Any]],
        active_allocations: list[dict[str, Any]] | set[str] | None = None,
        node_ids: list[str] | None = None,
    ) -> list[WorkerPlacementSpec]:
        """Compute random or explicitly selected placements for a training attempt.

        Args:
            expected_workers: Frozen membership count, or None for a first-start selection.
            nodes: List of node dictionaries containing node_id, state, and capabilities_jsonb.
            active_allocations: Active allocation rows or a set of busy node ids.

        Returns:
            List of exactly expected_workers WorkerPlacementSpec objects.

        Raises:
            NodeCapacityUnavailableError: If available online nodes are fewer than expected_workers.
            ValueError: If expected_workers <= 0.
        """
        if expected_workers is not None and (
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

        # Stable population ordering makes injected RNGs reproducible in tests.
        candidates.sort(key=lambda n: str(n.get("node_id", "")))

        if node_ids is not None:
            if not 1 <= len(node_ids) <= MANUAL_WORKER_LIMIT or len(set(node_ids)) != len(node_ids):
                raise ValueError("Select 1 to 5 distinct Nodes.")
            if expected_workers is not None and len(node_ids) != expected_workers:
                raise ValueError(
                    f"Select exactly {expected_workers} distinct Nodes for this frozen Job."
                )
            selected_ids = set(node_ids)
            candidates = [node for node in candidates if node["node_id"] in selected_ids]
            if {node["node_id"] for node in candidates} != selected_ids:
                raise NodeCapacityUnavailableError(
                    "Selected Nodes must all exist, be ONLINE and have no active allocation."
                )
            expected_workers = len(node_ids)
        else:
            if expected_workers is not None and expected_workers > AUTO_WORKER_LIMIT:
                raise ValueError(
                    f"This Job requires {expected_workers} Workers; select Nodes manually "
                    f"(automatic limit is {AUTO_WORKER_LIMIT})."
                )
            if expected_workers is None:
                expected_workers = min(AUTO_WORKER_LIMIT, len(candidates))
            if expected_workers == 0:
                raise NodeCapacityUnavailableError("No ONLINE, idle worker Nodes are available.")

        # 4. Check available capacity
        if len(candidates) < expected_workers:
            raise NodeCapacityUnavailableError(
                "Cluster has insufficient capacity: "
                f"{expected_workers} online worker node(s) required, "
                f"but only {len(candidates)} available."
            )

        # 5. Select exactly expected_workers nodes
        selected_nodes = sorted(
            random.sample(candidates, expected_workers), key=lambda n: str(n["node_id"])
        )

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
