"""Unit tests for ClusterScheduler (pure deterministic worker placement).

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1 & User Request Phase 5.
"""

from __future__ import annotations

import unittest

from pbl4.management_backend.services.cluster_scheduler import (
    ClusterScheduler,
    NodeCapacityUnavailableError,
    select_placements,
)


class TestClusterScheduler(unittest.TestCase):
    def setUp(self) -> None:
        self.scheduler = ClusterScheduler()

    def test_sufficient_nodes_selects_exact_count(self) -> None:
        nodes = [
            {"node_id": "node-01", "state": "ONLINE", "capabilities": {"gpus": []}},
            {"node_id": "node-02", "state": "ONLINE", "capabilities": {"gpus": []}},
            {"node_id": "node-03", "state": "ONLINE", "capabilities": {"gpus": []}},
            {"node_id": "node-04", "state": "ONLINE", "capabilities": {"gpus": []}},
        ]
        placements = select_placements(expected_workers=3, nodes=nodes)
        self.assertEqual(len(placements), 3)
        self.assertEqual(
            [p.node_id for p in placements],
            ["node-01", "node-02", "node-03"],
        )

    def test_offline_nodes_excluded(self) -> None:
        nodes = [
            {"node_id": "node-01", "state": "OFFLINE", "capabilities": {}},
            {"node_id": "node-02", "state": "ONLINE", "capabilities": {}},
            {"node_id": "node-03", "state": "OFFLINE", "capabilities": {}},
            {"node_id": "node-04", "state": "ONLINE", "capabilities": {}},
        ]
        placements = select_placements(expected_workers=2, nodes=nodes)
        self.assertEqual(len(placements), 2)
        self.assertEqual([p.node_id for p in placements], ["node-02", "node-04"])

    def test_revoked_nodes_excluded(self) -> None:
        nodes = [
            {"node_id": "node-01", "state": "REVOKED", "capabilities": {}},
            {"node_id": "node-02", "state": "ONLINE", "capabilities": {}},
            {"node_id": "node-03", "state": "REVOKED", "capabilities": {}},
            {"node_id": "node-04", "state": "ONLINE", "capabilities": {}},
        ]
        placements = select_placements(expected_workers=2, nodes=nodes)
        self.assertEqual([p.node_id for p in placements], ["node-02", "node-04"])

    def test_nodes_with_active_allocations_excluded(self) -> None:
        nodes = [
            {"node_id": "node-01", "state": "ONLINE", "capabilities": {}},
            {"node_id": "node-02", "state": "ONLINE", "capabilities": {}},
            {"node_id": "node-03", "state": "ONLINE", "capabilities": {}},
            {"node_id": "node-04", "state": "ONLINE", "capabilities": {}},
        ]
        # node-01 and node-03 are busy
        active_allocations = [
            {"allocation_id": "alloc-1", "node_id": "node-01", "actual_state": "STARTED"},
            {"allocation_id": "alloc-2", "node_id": "node-03", "actual_state": "REQUESTED"},
        ]
        placements = select_placements(
            expected_workers=2,
            nodes=nodes,
            active_allocations=active_allocations,
        )
        self.assertEqual([p.node_id for p in placements], ["node-02", "node-04"])

        # Also support set of string node IDs
        placements_set = select_placements(
            expected_workers=2,
            nodes=nodes,
            active_allocations={"node-01", "node-03"},
        )
        self.assertEqual([p.node_id for p in placements_set], ["node-02", "node-04"])

    def test_deterministic_sort_by_node_id(self) -> None:
        # Input out of order
        nodes = [
            {"node_id": "node-gamma", "state": "ONLINE", "capabilities": {}},
            {"node_id": "node-alpha", "state": "ONLINE", "capabilities": {}},
            {"node_id": "node-beta", "state": "ONLINE", "capabilities": {}},
        ]
        placements = select_placements(expected_workers=2, nodes=nodes)
        self.assertEqual(
            [p.node_id for p in placements],
            ["node-alpha", "node-beta"],
        )

    def test_insufficient_nodes_raises_node_capacity_unavailable(self) -> None:
        nodes = [
            {"node_id": "node-01", "state": "ONLINE", "capabilities": {}},
            {"node_id": "node-02", "state": "OFFLINE", "capabilities": {}},
        ]
        with self.assertRaises(NodeCapacityUnavailableError) as ctx:
            select_placements(expected_workers=2, nodes=nodes)

        self.assertEqual(ctx.exception.code, "NODE_CAPACITY_UNAVAILABLE")

    def test_gpu_capability_assigns_cuda0(self) -> None:
        nodes = [
            {
                "node_id": "node-gpu-1",
                "state": "ONLINE",
                "capabilities_jsonb": {"gpus": [{"index": 0, "name": "RTX 4090"}]},
            },
            {
                "node_id": "node-gpu-2",
                "state": "ONLINE",
                "capabilities": {"gpu_count": 1},
            },
        ]
        placements = select_placements(expected_workers=2, nodes=nodes)
        self.assertEqual(placements[0].device, "cuda:0")
        self.assertEqual(placements[1].device, "cuda:0")

    def test_no_gpu_assigns_cpu(self) -> None:
        nodes = [
            {
                "node_id": "node-cpu-1",
                "state": "ONLINE",
                "capabilities_jsonb": {"gpus": []},
            },
            {
                "node_id": "node-cpu-2",
                "state": "ONLINE",
                "capabilities": {},
            },
        ]
        placements = select_placements(expected_workers=2, nodes=nodes)
        self.assertEqual(placements[0].device, "cpu")
        self.assertEqual(placements[1].device, "cpu")

    def test_telemetry_metrics_do_not_affect_selection_order(self) -> None:
        # node-01 has 99% CPU load and 99% RAM load, but lexicographically precedes node-02
        nodes = [
            {
                "node_id": "node-02",
                "state": "ONLINE",
                "capabilities": {},
                "latest_resources_jsonb": {"cpu_utilization_pct": 5.0, "ram_used_bytes": 1000},
            },
            {
                "node_id": "node-01",
                "state": "ONLINE",
                "capabilities": {},
                "latest_resources_jsonb": {"cpu_utilization_pct": 99.0, "ram_used_bytes": 9999999},
            },
        ]
        placements = select_placements(expected_workers=2, nodes=nodes)
        # Strictly deterministic by node_id: node-01, then node-02
        self.assertEqual(
            [p.node_id for p in placements],
            ["node-01", "node-02"],
        )

    def test_pure_logic_no_side_effects(self) -> None:
        # Ensure scheduler does not mutate input dictionaries
        original_node = {"node_id": "node-01", "state": "ONLINE", "capabilities": {"gpus": []}}
        nodes = [original_node]
        select_placements(expected_workers=1, nodes=nodes)
        self.assertEqual(original_node["state"], "ONLINE")
        self.assertEqual(len(nodes), 1)

    def test_invalid_expected_workers_raises_value_error(self) -> None:
        nodes = [{"node_id": "node-01", "state": "ONLINE"}]
        with self.assertRaises(ValueError):
            select_placements(expected_workers=0, nodes=nodes)
        with self.assertRaises(ValueError):
            select_placements(expected_workers=-1, nodes=nodes)
        with self.assertRaises(ValueError):
            select_placements(expected_workers="3", nodes=nodes)  # type: ignore


if __name__ == "__main__":
    unittest.main()
