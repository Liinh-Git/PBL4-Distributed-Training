"""Unit tests for pbl4-agent CLI entrypoint (enroll, start, status).

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1 & User Request Phase 7.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pbl4.node_agent.entrypoint import main
from pbl4.node_agent.identity import NodeIdentity, load_identity, save_identity


def test_cli_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "pbl4-agent 0.1.0" in captured.out


def test_cli_status_not_enrolled(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["status", "--var-dir", str(tmp_path)])
    assert code == 0
    captured = capsys.readouterr()
    assert "Enrollment Status:  NOT ENROLLED" in captured.out
    assert "node_secret" not in captured.out


def test_cli_status_enrolled_redaction(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    save_identity(tmp_path, NodeIdentity(node_id="node-xyz-99", node_secret="super-secret-12345"))

    code = main(["status", "--var-dir", str(tmp_path)])
    assert code == 0
    captured = capsys.readouterr()
    assert "Enrollment Status:  ENROLLED" in captured.out
    assert "Node ID:            node-xyz-99" in captured.out
    # Security requirement: node_secret must NEVER be displayed
    assert "super-secret-12345" not in captured.out
    assert "secret" not in captured.out.lower()


def test_cli_start_requires_prior_enrollment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = main(["start", "--var-dir", str(tmp_path)])
    assert code == 1
    captured = capsys.readouterr()
    assert "Error: Node identity not found" in captured.err
    assert "pbl4-agent enroll" in captured.err


def test_cli_enroll_missing_code(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["enroll", "--var-dir", str(tmp_path), "--code", ""])
    assert code == 1
    captured = capsys.readouterr()
    assert "Enrollment code is required" in captured.err


@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_enroll_success(
    mock_enroll: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    mock_enroll.return_value = NodeIdentity(node_id="node-new-123", node_secret="secret-abc-789")

    code = main(
        [
            "enroll",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--code",
            "one-time-token",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    captured = capsys.readouterr()
    assert "Host successfully enrolled! Assigned node_id: node-new-123" in captured.out
    # Security: Secret never printed
    assert "secret-abc-789" not in captured.out
    assert "one-time-token" not in captured.out

    saved = load_identity(tmp_path)
    assert saved is not None
    assert saved.node_id == "node-new-123"
    assert saved.node_secret == "secret-abc-789"


@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_enroll_already_enrolled_blocks_unless_force(
    mock_enroll: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    save_identity(tmp_path, NodeIdentity(node_id="existing-node", node_secret="secret-old"))

    # Without --force -> blocked
    code = main(
        [
            "enroll",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--code",
            "one-time-token",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 1
    mock_enroll.assert_not_called()
    captured = capsys.readouterr()
    assert "Node is already enrolled with node_id='existing-node'" in captured.err

    # With --force -> allowed
    mock_enroll.return_value = NodeIdentity(node_id="overwritten-node", node_secret="secret-new")
    code_force = main(
        [
            "enroll",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--code",
            "one-time-token",
            "--var-dir",
            str(tmp_path),
            "--force",
        ]
    )
    assert code_force == 0
    mock_enroll.assert_called_once()
    saved = load_identity(tmp_path)
    assert saved is not None
    assert saved.node_id == "overwritten-node"
