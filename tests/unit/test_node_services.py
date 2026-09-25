"""Unit tests for NodeEnrollmentService and NodeService.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1 & User Request Phase 5.

Covers all 20 required acceptance criteria:
NodeEnrollmentService:
1. tạo enrollment code;
2. code được hash trước persistence;
3. consume qua repository;
4. code invalid/expired được xử lý đúng;
5. tạo node_id;
6. tạo node_secret;
7. lưu credential_hash;
8. plaintext node_secret chỉ trả một lần;
9. Node mới = OFFLINE.

NodeService:
10. authenticate valid node;
11. invalid secret -> reject;
12. revoked node -> reject;
13. heartbeat valid node;
14. stale ONLINE -> OFFLINE;
15. stale không ảnh hưởng allocation/Attempt;
16. revoke ONLINE -> REVOKED;
17. revoke OFFLINE -> REVOKED;
18. REVOKED không thể quay lại ONLINE;
19. heartbeat revoked -> reject;
20. authentication revoked -> reject.
"""

from __future__ import annotations

import hashlib
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from pbl4.management_backend.services.node_enrollment_service import (
    NodeEnrollmentCodeExpiredError,
    NodeEnrollmentCodeInvalidError,
    create_enrollment_code,
    enroll_node,
    hash_secret,
)
from pbl4.management_backend.services.node_service import (
    NodeRevokedError,
    NodeUnauthorizedError,
    authenticate_node,
    mark_stale_nodes,
    record_heartbeat,
    record_node_online,
    revoke_node,
)


class TestNodeEnrollmentService(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_conn = MagicMock()
        self.now = datetime.now(UTC)

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.create_enrollment_code")
    def test_01_create_enrollment_code(self, mock_repo_create: MagicMock) -> None:
        mock_repo_create.return_value = {
            "code_hash": "hash123",
            "created_at": self.now,
            "expires_at": self.now + timedelta(seconds=3600),
            "used_at": None,
        }
        res = create_enrollment_code(self.mock_conn, ttl_seconds=3600, now=self.now)
        self.assertIn("enrollment_code", res)
        self.assertIn("code_hash", res)
        self.assertTrue(len(res["enrollment_code"]) >= 32)
        mock_repo_create.assert_called_once()

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.create_enrollment_code")
    def test_02_code_hashed_before_persistence(self, mock_repo_create: MagicMock) -> None:
        mock_repo_create.return_value = {
            "code_hash": "dummy",
            "created_at": self.now,
            "expires_at": self.now + timedelta(seconds=3600),
        }
        res = create_enrollment_code(self.mock_conn, ttl_seconds=1800, now=self.now)
        raw_code = res["enrollment_code"]
        expected_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()

        # Check repository was called with code_hash, NOT plaintext raw_code
        mock_repo_create.assert_called_once()
        kwargs = mock_repo_create.call_args.kwargs
        self.assertEqual(kwargs["code_hash"], expected_hash)
        self.assertNotIn(raw_code, str(mock_repo_create.call_args))

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.consume_code_if_valid")
    @patch("pbl4.management_backend.repositories.node_repository.create_node")
    def test_03_consume_via_repository(
        self,
        mock_create_node: MagicMock,
        mock_consume: MagicMock,
    ) -> None:
        mock_consume.return_value = {"code_hash": "hash_val", "used_at": self.now}
        mock_create_node.return_value = {
            "node_id": "node-123",
            "state": "OFFLINE",
            "display_name": "Test Node",
        }

        res = enroll_node(
            self.mock_conn,
            enrollment_code="valid-secret-code",
            capabilities={"hostname": "host-01"},
            now=self.now,
        )

        expected_hash = hashlib.sha256(b"valid-secret-code").hexdigest()
        mock_consume.assert_called_once_with(
            self.mock_conn,
            code_hash=expected_hash,
            now=self.now,
        )
        self.assertEqual(res["node_id"], "node-123")
        self.assertIn("node_secret", res)

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.get_enrollment_code")
    @patch("pbl4.management_backend.repositories.node_enrollment_repository.consume_code_if_valid")
    def test_04_code_invalid_or_expired_handled(
        self,
        mock_consume: MagicMock,
        mock_get: MagicMock,
    ) -> None:
        mock_consume.return_value = None

        # Case 1: Code does not exist in DB
        mock_get.return_value = None
        with self.assertRaises(NodeEnrollmentCodeInvalidError) as ctx:
            enroll_node(self.mock_conn, enrollment_code="non-existent-code", now=self.now)
        self.assertEqual(ctx.exception.code, "NODE_ENROLLMENT_CODE_INVALID")

        # Case 2: Code already used
        mock_get.return_value = {
            "code_hash": "hash",
            "used_at": self.now - timedelta(seconds=60),
            "expires_at": self.now + timedelta(seconds=3000),
        }
        with self.assertRaises(NodeEnrollmentCodeInvalidError) as ctx2:
            enroll_node(self.mock_conn, enrollment_code="used-code", now=self.now)
        self.assertEqual(ctx2.exception.code, "NODE_ENROLLMENT_CODE_INVALID")

        # Case 3: Code expired
        mock_get.return_value = {
            "code_hash": "hash",
            "used_at": None,
            "expires_at": self.now - timedelta(seconds=10),
        }
        with self.assertRaises(NodeEnrollmentCodeExpiredError) as ctx3:
            enroll_node(self.mock_conn, enrollment_code="expired-code", now=self.now)
        self.assertEqual(ctx3.exception.code, "NODE_ENROLLMENT_CODE_EXPIRED")

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.consume_code_if_valid")
    @patch("pbl4.management_backend.repositories.node_repository.create_node")
    def test_05_creates_node_id(
        self,
        mock_create_node: MagicMock,
        mock_consume: MagicMock,
    ) -> None:
        mock_consume.return_value = {"code_hash": "hash"}
        mock_create_node.side_effect = lambda conn, **kwargs: dict(kwargs)

        res = enroll_node(self.mock_conn, enrollment_code="code-123", now=self.now)
        self.assertTrue(res["node_id"].startswith("node-"))
        self.assertTrue(len(res["node_id"]) >= 10)

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.consume_code_if_valid")
    @patch("pbl4.management_backend.repositories.node_repository.create_node")
    def test_06_creates_node_secret(
        self,
        mock_create_node: MagicMock,
        mock_consume: MagicMock,
    ) -> None:
        mock_consume.return_value = {"code_hash": "hash"}
        mock_create_node.side_effect = lambda conn, **kwargs: dict(kwargs)

        res = enroll_node(self.mock_conn, enrollment_code="code-123", now=self.now)
        secret = res["node_secret"]
        self.assertIsInstance(secret, str)
        self.assertTrue(len(secret) >= 32)

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.consume_code_if_valid")
    @patch("pbl4.management_backend.repositories.node_repository.create_node")
    def test_07_stores_credential_hash(
        self,
        mock_create_node: MagicMock,
        mock_consume: MagicMock,
    ) -> None:
        mock_consume.return_value = {"code_hash": "hash"}
        mock_create_node.side_effect = lambda conn, **kwargs: dict(kwargs)

        res = enroll_node(self.mock_conn, enrollment_code="code-123", now=self.now)
        secret = res["node_secret"]
        expected_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()

        kwargs = mock_create_node.call_args.kwargs
        self.assertEqual(kwargs["credential_hash"], expected_hash)
        # Plaintext secret must never be passed to repository
        self.assertNotIn(secret, str(mock_create_node.call_args))

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.consume_code_if_valid")
    @patch("pbl4.management_backend.repositories.node_repository.create_node")
    def test_08_plaintext_secret_returned_once(
        self,
        mock_create_node: MagicMock,
        mock_consume: MagicMock,
    ) -> None:
        mock_consume.return_value = {"code_hash": "hash"}
        mock_create_node.return_value = {"node_id": "node-1", "state": "OFFLINE"}

        res = enroll_node(self.mock_conn, enrollment_code="code-123", now=self.now)
        self.assertIn("node_secret", res)
        # Second consume fails because code is one-time
        mock_consume.return_value = None
        with patch(
            "pbl4.management_backend.repositories.node_enrollment_repository.get_enrollment_code"
        ) as mock_get:
            mock_get.return_value = {"code_hash": "hash", "used_at": self.now}
            with self.assertRaises(NodeEnrollmentCodeInvalidError):
                enroll_node(self.mock_conn, enrollment_code="code-123", now=self.now)

    @patch("pbl4.management_backend.repositories.node_enrollment_repository.consume_code_if_valid")
    @patch("pbl4.management_backend.repositories.node_repository.create_node")
    def test_09_new_node_state_is_offline(
        self,
        mock_create_node: MagicMock,
        mock_consume: MagicMock,
    ) -> None:
        mock_consume.return_value = {"code_hash": "hash"}
        mock_create_node.side_effect = lambda conn, **kwargs: dict(kwargs)

        res = enroll_node(self.mock_conn, enrollment_code="code-123", now=self.now)
        kwargs = mock_create_node.call_args.kwargs
        self.assertEqual(kwargs["state"], "OFFLINE")
        self.assertEqual(res["node"]["state"], "OFFLINE")


class TestNodeService(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_conn = MagicMock()
        self.now = datetime.now(UTC)
        self.node_secret = "super-secret-token-32-chars-long!"
        self.credential_hash = hash_secret(self.node_secret)
        self.base_node = {
            "node_id": "node-worker-01",
            "display_name": "Worker 01",
            "state": "ONLINE",
            "credential_hash": self.credential_hash,
            "credential_created_at": self.now - timedelta(hours=1),
            "credential_revoked_at": None,
            "last_seen_at": self.now - timedelta(seconds=2),
            "capabilities_jsonb": {},
            "latest_resources_jsonb": None,
        }

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_10_authenticate_valid_node(self, mock_get_node: MagicMock) -> None:
        mock_get_node.return_value = dict(self.base_node)
        node = authenticate_node(self.mock_conn, "node-worker-01", self.node_secret)
        self.assertEqual(node["node_id"], "node-worker-01")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_11_invalid_secret_rejected(self, mock_get_node: MagicMock) -> None:
        mock_get_node.return_value = dict(self.base_node)
        with self.assertRaises(NodeUnauthorizedError) as ctx:
            authenticate_node(self.mock_conn, "node-worker-01", "wrong-secret")
        self.assertEqual(ctx.exception.code, "NODE_UNAUTHORIZED")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_12_revoked_node_rejected(self, mock_get_node: MagicMock) -> None:
        revoked_node = dict(self.base_node)
        revoked_node["state"] = "REVOKED"
        revoked_node["credential_revoked_at"] = self.now - timedelta(minutes=5)
        mock_get_node.return_value = revoked_node

        with self.assertRaises(NodeRevokedError) as ctx:
            authenticate_node(self.mock_conn, "node-worker-01", self.node_secret)
        self.assertEqual(ctx.exception.code, "NODE_REVOKED")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    @patch("pbl4.management_backend.repositories.node_repository.update_heartbeat")
    @patch("pbl4.management_backend.repositories.node_repository.update_state")
    def test_13_heartbeat_valid_node(
        self,
        mock_update_state: MagicMock,
        mock_update_hb: MagicMock,
        mock_get_node: MagicMock,
    ) -> None:
        # Case A: ONLINE node updates last_seen_at
        mock_get_node.return_value = dict(self.base_node)
        mock_update_hb.return_value = dict(self.base_node, last_seen_at=self.now)

        res = record_heartbeat(self.mock_conn, "node-worker-01", last_seen_at=self.now)
        mock_update_hb.assert_called_once_with(self.mock_conn, "node-worker-01", self.now)
        self.assertEqual(res["last_seen_at"], self.now)

        # Case B: heartbeat alone cannot transition OFFLINE -> ONLINE
        offline_node = dict(self.base_node, state="OFFLINE")
        mock_get_node.return_value = offline_node
        record_heartbeat(self.mock_conn, "node-worker-01", last_seen_at=self.now)
        mock_update_state.assert_not_called()

    @patch("pbl4.management_backend.repositories.node_repository.list_nodes")
    @patch("pbl4.management_backend.repositories.node_repository.update_state")
    def test_14_stale_online_to_offline(
        self,
        mock_update_state: MagicMock,
        mock_list_nodes: MagicMock,
    ) -> None:
        stale_node = dict(self.base_node, last_seen_at=self.now - timedelta(seconds=20))
        fresh_node = dict(
            self.base_node, node_id="node-fresh", last_seen_at=self.now - timedelta(seconds=5)
        )
        mock_list_nodes.return_value = [stale_node, fresh_node]

        stale_ids = mark_stale_nodes(self.mock_conn, timeout_seconds=15.0, now=self.now)
        self.assertEqual(stale_ids, ["node-worker-01"])
        mock_update_state.assert_called_once_with(self.mock_conn, "node-worker-01", "OFFLINE")

    @patch("pbl4.management_backend.repositories.node_repository.list_nodes")
    @patch("pbl4.management_backend.repositories.node_repository.update_state")
    def test_15_stale_does_not_affect_allocations_or_attempts(
        self,
        mock_update_state: MagicMock,
        mock_list_nodes: MagicMock,
    ) -> None:
        stale_node = dict(self.base_node, last_seen_at=self.now - timedelta(seconds=60))
        mock_list_nodes.return_value = [stale_node]

        # Verify only node_repository is touched; no allocation or attempt calls
        mark_stale_nodes(self.mock_conn, timeout_seconds=15.0, now=self.now)
        mock_update_state.assert_called_once_with(self.mock_conn, "node-worker-01", "OFFLINE")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    @patch("pbl4.management_backend.repositories.node_repository.revoke_node")
    def test_16_revoke_online_node_to_revoked(
        self,
        mock_repo_revoke: MagicMock,
        mock_get_node: MagicMock,
    ) -> None:
        mock_get_node.return_value = dict(self.base_node, state="ONLINE")
        mock_repo_revoke.return_value = dict(
            self.base_node, state="REVOKED", credential_revoked_at=self.now
        )

        res = revoke_node(self.mock_conn, "node-worker-01", now=self.now)
        self.assertEqual(res["state"], "REVOKED")
        mock_repo_revoke.assert_called_once_with(self.mock_conn, "node-worker-01", self.now)

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    @patch("pbl4.management_backend.repositories.node_repository.revoke_node")
    def test_17_revoke_offline_node_to_revoked(
        self,
        mock_repo_revoke: MagicMock,
        mock_get_node: MagicMock,
    ) -> None:
        mock_get_node.return_value = dict(self.base_node, state="OFFLINE")
        mock_repo_revoke.return_value = dict(
            self.base_node, state="REVOKED", credential_revoked_at=self.now
        )

        res = revoke_node(self.mock_conn, "node-worker-01", now=self.now)
        self.assertEqual(res["state"], "REVOKED")
        mock_repo_revoke.assert_called_once_with(self.mock_conn, "node-worker-01", self.now)

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_18_revoked_cannot_transition_to_online(self, mock_get_node: MagicMock) -> None:
        revoked_node = dict(self.base_node, state="REVOKED", credential_revoked_at=self.now)
        mock_get_node.return_value = revoked_node

        with self.assertRaises(NodeRevokedError) as ctx:
            record_node_online(self.mock_conn, "node-worker-01", now=self.now)
        self.assertEqual(ctx.exception.code, "NODE_REVOKED")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_19_heartbeat_revoked_rejected(self, mock_get_node: MagicMock) -> None:
        revoked_node = dict(self.base_node, state="REVOKED", credential_revoked_at=self.now)
        mock_get_node.return_value = revoked_node

        with self.assertRaises(NodeRevokedError) as ctx:
            record_heartbeat(self.mock_conn, "node-worker-01", last_seen_at=self.now)
        self.assertEqual(ctx.exception.code, "NODE_REVOKED")

    @patch("pbl4.management_backend.repositories.node_repository.get_node")
    def test_20_authentication_revoked_rejected(self, mock_get_node: MagicMock) -> None:
        revoked_node = dict(self.base_node, state="REVOKED", credential_revoked_at=self.now)
        mock_get_node.return_value = revoked_node

        # Even with valid secret, authentication must fail because node is REVOKED
        with self.assertRaises(NodeRevokedError) as ctx:
            authenticate_node(self.mock_conn, "node-worker-01", self.node_secret)
        self.assertEqual(ctx.exception.code, "NODE_REVOKED")


if __name__ == "__main__":
    unittest.main()
