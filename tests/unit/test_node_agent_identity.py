"""Unit tests for Node Agent Identity, Configuration, and Enrollment.

Reference: Phase 3 requirements in NODE_AGENT_IMPLEMENTATION_PLAN.md
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from pbl4.node_agent.config import NodeAgentConfig
from pbl4.node_agent.enrollment import enroll
from pbl4.node_agent.identity import (
    NodeIdentity,
    identity_path,
    load_identity,
    save_identity,
)


class TestNodeIdentity(unittest.TestCase):
    """Test cases for NodeIdentity and local persistence."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.var_dir = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_1_save_and_load_identity(self) -> None:
        identity = NodeIdentity(node_id="node-test-123", node_secret="sec-secret-token-xyz")
        saved_path = save_identity(self.var_dir, identity)
        self.assertTrue(saved_path.is_file())

        loaded = load_identity(self.var_dir)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.node_id, "node-test-123")
        self.assertEqual(loaded.node_secret, "sec-secret-token-xyz")

    def test_2_identity_path(self) -> None:
        path = identity_path(self.var_dir)
        self.assertEqual(path, self.var_dir / "node_identity.json")

    def test_3_missing_identity_returns_none(self) -> None:
        loaded = load_identity(self.var_dir)
        self.assertIsNone(loaded)

    def test_4_malformed_identity_raises_value_error(self) -> None:
        path = identity_path(self.var_dir)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Invalid JSON
        path.write_text("not-a-json", encoding="utf-8")
        with self.assertRaises(ValueError):
            load_identity(self.var_dir)

        # Missing node_secret
        path.write_text(json.dumps({"node_id": "n1"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_identity(self.var_dir)

        # Empty node_id
        path.write_text(json.dumps({"node_id": "", "node_secret": "s1"}), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_identity(self.var_dir)

    def test_5_posix_permission_behavior(self) -> None:
        identity = NodeIdentity(node_id="node-posix", node_secret="posix-secret")
        if os.name != "nt":
            saved_path = save_identity(self.var_dir, identity)
            mode = saved_path.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
        else:
            # On Windows, save_identity succeeds cleanly without failing
            saved_path = save_identity(self.var_dir, identity)
            self.assertTrue(saved_path.is_file())

    def test_6_secret_not_in_repr(self) -> None:
        secret = "ultra-secret-key-12345"
        identity = NodeIdentity(node_id="node-1", node_secret=secret)
        repr_str = repr(identity)
        self.assertNotIn(secret, repr_str)
        self.assertIn("***REDACTED***", repr_str)
        self.assertIn("node-1", repr_str)

    def test_identity_validation_non_empty(self) -> None:
        with self.assertRaises(ValueError):
            NodeIdentity(node_id="", node_secret="secret")
        with self.assertRaises(ValueError):
            NodeIdentity(node_id="node", node_secret="")


class TestNodeEnrollment(unittest.TestCase):
    """Test cases for one-time enrollment client."""

    @patch("urllib.request.urlopen")
    def test_enroll_success_direct_payload(self, mock_urlopen: MagicMock) -> None:
        resp_data = {"node_id": "node-enrolled-1", "node_secret": "secret-new-123"}
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        identity = enroll("http://127.0.0.1:8000", "code-one-time-123", {"gpu": "rtx4090"})
        self.assertEqual(identity.node_id, "node-enrolled-1")
        self.assertEqual(identity.node_secret, "secret-new-123")

        # Verify request headers
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.headers.get("Authorization"), "Bearer code-one-time-123")
        self.assertEqual(req.headers.get("Content-type"), "application/json")

    @patch("urllib.request.urlopen")
    def test_enroll_success_wrapped_data_envelope(self, mock_urlopen: MagicMock) -> None:
        resp_data = {"data": {"node_id": "node-wrapped", "node_secret": "secret-wrapped"}}
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 201
        mock_resp.read.return_value = json.dumps(resp_data).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        identity = enroll("http://127.0.0.1:8000", "code-envelope")
        self.assertEqual(identity.node_id, "node-wrapped")
        self.assertEqual(identity.node_secret, "secret-wrapped")

    @patch("urllib.request.urlopen")
    def test_enroll_http_error(self, mock_urlopen: MagicMock) -> None:
        mock_urlopen.side_effect = urllib.error.HTTPError(
            url="http://test",
            code=401,
            msg="Unauthorized",
            hdrs=None,  # type: ignore[arg-type]
            fp=io.BytesIO(b"Unauthorized code"),
        )

        with self.assertRaises(RuntimeError) as ctx:
            enroll("http://127.0.0.1:8000", "code-invalid")
        self.assertIn("401", str(ctx.exception))
        # Ensure enrollment code is not leaked in exception
        self.assertNotIn("code-invalid", str(ctx.exception))

    @patch("urllib.request.urlopen")
    def test_enroll_malformed_response_raises_value_error(self, mock_urlopen: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_resp.read.return_value = b"invalid json data"
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        with self.assertRaises(ValueError):
            enroll("http://127.0.0.1:8000", "code-valid")

    def test_enroll_invalid_arguments(self) -> None:
        with self.assertRaises(ValueError):
            enroll("", "code-1")
        with self.assertRaises(ValueError):
            enroll("http://127.0.0.1:8000", "")


class TestNodeAgentConfig(unittest.TestCase):
    """Test cases for NodeAgentConfig."""

    def test_config_defaults_and_validation(self) -> None:
        config = NodeAgentConfig(backend_url="http://127.0.0.1:8000")
        self.assertEqual(config.backend_url, "http://127.0.0.1:8000")
        self.assertEqual(config.var_dir, "var/agent")
        self.assertEqual(config.heartbeat_interval_seconds, 5.0)
        self.assertEqual(config.telemetry_interval_seconds, 10.0)

        # Invalid backend url
        with self.assertRaises(ValueError):
            NodeAgentConfig(backend_url="")

        # Invalid intervals
        with self.assertRaises(ValueError):
            NodeAgentConfig(backend_url="http://test", heartbeat_interval_seconds=-1.0)
        with self.assertRaises(ValueError):
            NodeAgentConfig(
                backend_url="http://test", reconnect_min_seconds=10.0, reconnect_max_seconds=5.0
            )

    def test_config_from_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "PBL4_BACKEND_URL": "http://node-backend:9000",
                "PBL4_VAR_DIR": "custom/var",
                "PBL4_HEARTBEAT_INTERVAL_SECONDS": "7.5",
                "PBL4_TELEMETRY_INTERVAL_SECONDS": "15.0",
                "PBL4_LOG_LEVEL": "DEBUG",
            },
        ):
            config = NodeAgentConfig.from_env()
            self.assertEqual(config.backend_url, "http://node-backend:9000")
            self.assertEqual(config.var_dir, "custom/var")
            self.assertEqual(config.heartbeat_interval_seconds, 7.5)
            self.assertEqual(config.telemetry_interval_seconds, 15.0)
            self.assertEqual(config.log_level, "DEBUG")


if __name__ == "__main__":
    unittest.main()
