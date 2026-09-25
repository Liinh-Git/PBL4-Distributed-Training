"""Unit tests for AllocationService.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1 & User Request Phase 5.

Covers:
- create allocation
- OFFLINE target rejection
- REVOKED target rejection
- attempt/allocation validation
- seed extraction from resolved_contract
- seed type validation (strictly int, no bool/float/str)
- join token generation & claims verification
- correct runtime advertised host/port
- state transitions (REQUESTED -> DISPATCHED -> STARTED -> ENDED / FAILED)
- missing admission secret failure
- stop allocation semantics (desired_state STOPPED, gateway call, no attempt mutation)
- timeout DISPATCHED allocations
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from pbl4.common.worker_admission import verify_worker_join_token
from pbl4.management_backend.config import BackendSettings
from pbl4.management_backend.services.allocation_service import (
    WorkerAdmissionConfigError,
    build_start_worker_command,
    create_allocation,
    create_allocations_for_attempt,
    dispatch_allocation,
    fail_timed_out_dispatched_allocations,
    record_dispatched,
    record_ended,
    record_failed,
    record_started,
    stop_allocation,
)
from pbl4.management_backend.services.cluster_scheduler import WorkerPlacementSpec
from pbl4.management_backend.services.node_service import (
    NodeNotFoundError,
    NodeOfflineError,
    NodeRevokedError,
)


class TestAllocationService(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_conn = MagicMock()
        self.now = datetime.now(UTC)
        self.settings = BackendSettings(
            PBL4_WORKER_ADMISSION_SECRET="test-admission-secret-key-32-chars!",
            RUNTIME_HOST="127.0.0.1",
            RUNTIME_ADVERTISED_HOST="192.168.1.100",
            RUNTIME_PORT=9000,
            WORKER_JOIN_TOKEN_TTL_SECONDS=300,
            WORKER_START_TIMEOUT_SECONDS=60.0,
        )
        self.base_node = {
            "node_id": "node-worker-01",
            "state": "ONLINE",
            "capabilities_jsonb": {},
        }
        self.base_job = {
            "job_id": "job-01",
            "resolved_contract": {
                "training": {
                    "training_seed": 123456,
                },
                "synchronization": {
                    "expected_workers": 2,
                },
            },
        }
        self.base_allocation = {
            "allocation_id": "alloc-001",
            "attempt_id": "attempt-01",
            "node_id": "node-worker-01",
            "desired_state": "RUNNING",
            "actual_state": "REQUESTED",
            "device": "cuda:0",
            "runtime_endpoint": "192.168.1.100:9000",
            "created_at": self.now,
            "dispatched_at": None,
            "started_at": None,
            "ended_at": None,
            "failure_code": None,
            "failure_message": None,
        }

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    @patch("pbl4.management_backend.repositories.allocation_repository.create_allocation")
    def test_create_allocation_success(
        self,
        mock_repo_create: MagicMock,
        mock_get_node: MagicMock,
    ) -> None:
        mock_get_node.return_value = dict(self.base_node)
        mock_repo_create.return_value = dict(self.base_allocation)

        res = create_allocation(
            self.mock_conn,
            attempt_id="attempt-01",
            node_id="node-worker-01",
            device="cuda:0",
            allocation_id="alloc-001",
            settings=self.settings,
            now=self.now,
        )

        mock_get_node.assert_called_once_with(self.mock_conn, "node-worker-01")
        mock_repo_create.assert_called_once()
        kwargs = mock_repo_create.call_args.kwargs
        self.assertEqual(kwargs["desired_state"], "RUNNING")
        self.assertEqual(kwargs["actual_state"], "REQUESTED")
        self.assertEqual(kwargs["runtime_endpoint"], "192.168.1.100:9000")
        self.assertEqual(res["allocation_id"], "alloc-001")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_create_allocation_rejects_offline_node(self, mock_get_node: MagicMock) -> None:
        mock_get_node.return_value = dict(self.base_node, state="OFFLINE")

        with self.assertRaises(NodeOfflineError) as ctx:
            create_allocation(
                self.mock_conn,
                attempt_id="attempt-01",
                node_id="node-worker-01",
                device="cuda:0",
                settings=self.settings,
            )
        self.assertEqual(ctx.exception.code, "NODE_OFFLINE")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_create_allocation_rejects_revoked_node(self, mock_get_node: MagicMock) -> None:
        mock_get_node.return_value = dict(self.base_node, state="REVOKED")

        with self.assertRaises(NodeRevokedError) as ctx:
            create_allocation(
                self.mock_conn,
                attempt_id="attempt-01",
                node_id="node-worker-01",
                device="cuda:0",
                settings=self.settings,
            )
        self.assertEqual(ctx.exception.code, "NODE_REVOKED")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_create_allocation_rejects_nonexistent_node(self, mock_get_node: MagicMock) -> None:
        mock_get_node.return_value = None

        with self.assertRaises(NodeNotFoundError) as ctx:
            create_allocation(
                self.mock_conn,
                attempt_id="attempt-01",
                node_id="node-nonexistent",
                device="cpu",
                settings=self.settings,
            )
        self.assertEqual(ctx.exception.code, "NODE_NOT_FOUND")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    @patch("pbl4.management_backend.repositories.allocation_repository.create_allocation")
    def test_create_allocations_for_attempt(
        self,
        mock_repo_create: MagicMock,
        mock_get_node: MagicMock,
    ) -> None:
        mock_get_node.return_value = dict(self.base_node)
        mock_repo_create.side_effect = lambda conn, **kwargs: dict(kwargs)

        placements = [
            WorkerPlacementSpec(node_id="node-worker-01", device="cuda:0"),
            WorkerPlacementSpec(node_id="node-worker-02", device="cpu"),
        ]

        res = create_allocations_for_attempt(
            self.mock_conn,
            attempt_id="attempt-01",
            placements=placements,
            settings=self.settings,
            now=self.now,
        )

        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]["device"], "cuda:0")
        self.assertEqual(res[1]["device"], "cpu")

    def test_build_start_worker_command_success(self) -> None:
        cmd = build_start_worker_command(
            allocation=self.base_allocation,
            job=self.base_job,
            settings=self.settings,
        )

        self.assertEqual(cmd.command_type, "START_WORKER")
        self.assertEqual(cmd.allocation_id, "alloc-001")
        self.assertEqual(cmd.attempt_id, "attempt-01")
        self.assertEqual(cmd.runtime_host, "192.168.1.100")
        self.assertEqual(cmd.runtime_port, 9000)
        self.assertEqual(cmd.device, "cuda:0")
        self.assertEqual(cmd.initialization_seed, 123456)
        self.assertTrue(len(cmd.worker_join_token) > 0)

    def test_seed_extraction_and_type_validation(self) -> None:
        # 1. Valid seed extraction from JSON string resolved_contract
        job_with_json_str = {
            "job_id": "job-02",
            "resolved_contract": json.dumps({"training": {"training_seed": 777}}),
        }
        cmd = build_start_worker_command(
            allocation=self.base_allocation,
            job=job_with_json_str,
            settings=self.settings,
        )
        self.assertEqual(cmd.initialization_seed, 777)

        # 2. Missing training_seed
        job_no_seed = {"resolved_contract": {"training": {}}}
        with self.assertRaises(ValueError):
            build_start_worker_command(
                allocation=self.base_allocation,
                job=job_no_seed,
                settings=self.settings,
            )

        # 3. Seed is boolean (bool is instance of int in Python, must be rejected)
        job_bool_seed = {"resolved_contract": {"training": {"training_seed": True}}}
        with self.assertRaises(ValueError):
            build_start_worker_command(
                allocation=self.base_allocation,
                job=job_bool_seed,
                settings=self.settings,
            )

        # 4. Seed is float or string
        job_float_seed = {"resolved_contract": {"training": {"training_seed": 42.5}}}
        with self.assertRaises(ValueError):
            build_start_worker_command(
                allocation=self.base_allocation,
                job=job_float_seed,
                settings=self.settings,
            )

    def test_worker_join_token_claims_verification(self) -> None:
        cmd = build_start_worker_command(
            allocation=self.base_allocation,
            job=self.base_job,
            settings=self.settings,
        )

        claims = verify_worker_join_token(
            secret=self.settings.worker_admission_secret,
            token=cmd.worker_join_token,
            expected_attempt_id="attempt-01",
            expected_allocation_id="alloc-001",
            expected_node_id="node-worker-01",
        )
        self.assertEqual(claims.attempt_id, "attempt-01")
        self.assertEqual(claims.allocation_id, "alloc-001")
        self.assertEqual(claims.node_id, "node-worker-01")

    def test_missing_admission_secret_raises_config_error(self) -> None:
        no_secret_settings = BackendSettings(
            PBL4_WORKER_ADMISSION_SECRET=None,
            RUNTIME_HOST="127.0.0.1",
            RUNTIME_PORT=9000,
        )
        with self.assertRaises(WorkerAdmissionConfigError) as ctx:
            build_start_worker_command(
                allocation=self.base_allocation,
                job=self.base_job,
                settings=no_secret_settings,
            )
        self.assertEqual(ctx.exception.code, "WORKER_ADMISSION_CONFIG_ERROR")

    def test_attempt_allocation_mismatch_rejected(self) -> None:
        wrong_attempt = {
            "attempt_id": "attempt-OTHER-999",
            "resolved_contract": self.base_job["resolved_contract"],
        }
        with self.assertRaises(ValueError):
            build_start_worker_command(
                allocation=self.base_allocation,
                attempt=wrong_attempt,
                settings=self.settings,
            )

    @patch("pbl4.management_backend.repositories.allocation_repository.update_actual_state")
    @patch("pbl4.management_backend.repositories.allocation_repository.terminal_update")
    @patch("pbl4.management_backend.services.allocation_service.AllocationService.get_allocation")
    def test_state_transitions(
        self,
        mock_get_alloc: MagicMock,
        mock_terminal_update: MagicMock,
        mock_update_actual: MagicMock,
    ) -> None:
        mock_get_alloc.return_value = dict(self.base_allocation)

        # 1. DISPATCHED
        record_dispatched(self.mock_conn, "alloc-001", dispatched_at=self.now)
        mock_update_actual.assert_called_with(
            self.mock_conn,
            "alloc-001",
            "DISPATCHED",
            dispatched_at=self.now,
        )

        # 2. STARTED
        record_started(self.mock_conn, "alloc-001", started_at=self.now)
        mock_update_actual.assert_called_with(
            self.mock_conn,
            "alloc-001",
            "STARTED",
            started_at=self.now,
        )

        # 3. ENDED
        record_ended(self.mock_conn, "alloc-001", ended_at=self.now)
        mock_terminal_update.assert_called_with(
            self.mock_conn,
            "alloc-001",
            "ENDED",
            ended_at=self.now,
        )

        # 4. FAILED
        record_failed(
            self.mock_conn,
            "alloc-001",
            failure_code="WORKER_CRASHED",
            failure_message="SIGSEGV",
            ended_at=self.now,
        )
        mock_terminal_update.assert_called_with(
            self.mock_conn,
            "alloc-001",
            "FAILED",
            ended_at=self.now,
            failure_code="WORKER_CRASHED",
            failure_message="SIGSEGV",
        )

    @patch("pbl4.management_backend.repositories.allocation_repository.update_actual_state")
    @patch("pbl4.management_backend.services.allocation_service.AllocationService.get_allocation")
    def test_dispatch_allocation_via_gateway(
        self,
        mock_get_alloc: MagicMock,
        mock_update_actual: MagicMock,
    ) -> None:
        mock_get_alloc.return_value = dict(self.base_allocation)
        cmd = build_start_worker_command(
            allocation=self.base_allocation,
            job=self.base_job,
            settings=self.settings,
        )

        # Case A: Gateway transmission succeeds -> DISPATCHED
        mock_gateway = MagicMock()
        mock_gateway.send_start_worker.return_value = True

        dispatch_allocation(
            self.mock_conn,
            "alloc-001",
            command=cmd,
            gateway=mock_gateway,
            now=self.now,
        )
        mock_gateway.send_start_worker.assert_called_once_with("node-worker-01", command=cmd)
        mock_update_actual.assert_called_with(
            self.mock_conn,
            "alloc-001",
            "DISPATCHED",
            dispatched_at=self.now,
        )

        # Case B: Gateway transmission fails -> FAILED
        mock_gateway.send_start_worker.return_value = False
        dispatch_allocation(
            self.mock_conn,
            "alloc-001",
            command=cmd,
            gateway=mock_gateway,
            now=self.now,
        )
        mock_update_actual.assert_called_with(
            self.mock_conn,
            "alloc-001",
            "FAILED",
            ended_at=self.now,
            failure_code="NODE_DISPATCH_FAILED",
            failure_message="Failed to transmit START_WORKER to node agent 'node-worker-01'.",
        )

    @patch("pbl4.management_backend.repositories.allocation_repository.update_desired_state")
    @patch("pbl4.management_backend.services.allocation_service.AllocationService.get_allocation")
    def test_stop_allocation_semantics(
        self,
        mock_get_alloc: MagicMock,
        mock_update_desired: MagicMock,
    ) -> None:
        mock_get_alloc.return_value = dict(self.base_allocation)
        mock_gateway = MagicMock()

        stop_allocation(
            self.mock_conn,
            "alloc-001",
            gateway=mock_gateway,
            grace_period_seconds=15.0,
            force=True,
            now=self.now,
        )

        # Desired state updated to STOPPED
        mock_update_desired.assert_called_once_with(self.mock_conn, "alloc-001", "STOPPED")
        mock_gateway.send_stop_worker.assert_called_once()
        cmd_arg = mock_gateway.send_stop_worker.call_args.kwargs["command"]
        self.assertEqual(cmd_arg.allocation_id, "alloc-001")
        self.assertEqual(cmd_arg.grace_period_seconds, 15.0)
        self.assertTrue(cmd_arg.force)

    @patch("pbl4.management_backend.repositories.allocation_repository.list_active")
    @patch("pbl4.management_backend.repositories.allocation_repository.terminal_update")
    def test_fail_timed_out_dispatched_allocations(
        self,
        mock_terminal_update: MagicMock,
        mock_list_active: MagicMock,
    ) -> None:
        timed_out_alloc = {
            "allocation_id": "alloc-timeout",
            "actual_state": "DISPATCHED",
            "dispatched_at": self.now - timedelta(seconds=120),
        }
        fresh_dispatched_alloc = {
            "allocation_id": "alloc-fresh",
            "actual_state": "DISPATCHED",
            "dispatched_at": self.now - timedelta(seconds=10),
        }
        started_alloc = {
            "allocation_id": "alloc-started",
            "actual_state": "STARTED",
            "dispatched_at": self.now - timedelta(seconds=200),
        }

        mock_list_active.return_value = [
            timed_out_alloc,
            fresh_dispatched_alloc,
            started_alloc,
        ]

        failed_ids = fail_timed_out_dispatched_allocations(
            self.mock_conn,
            timeout_seconds=60.0,
            now=self.now,
        )

        self.assertEqual(failed_ids, ["alloc-timeout"])
        mock_terminal_update.assert_called_once_with(
            self.mock_conn,
            "alloc-timeout",
            "FAILED",
            ended_at=self.now,
            failure_code="WORKER_START_TIMEOUT",
            failure_message="Timed out waiting for WORKER_STATUS STARTED from node agent.",
        )


if __name__ == "__main__":
    unittest.main()
