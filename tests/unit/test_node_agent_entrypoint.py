"""Unit tests for pbl4-agent CLI entrypoint (enroll, start, status).

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md Section 8.1 & User Request Phase 7.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from pbl4.node_agent.enrollment import EnrollmentError
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
def test_cli_enroll_already_enrolled_rejects_force_and_prevents_ghost_nodes(
    mock_enroll: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 6: Existing identity + --force must NOT silently create a new Node or overwrite identity."""
    save_identity(tmp_path, NodeIdentity(node_id="existing-node", node_secret="secret-old"))

    # Without --force -> blocked, reuses identity without enrolling
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

    # With --force -> rejected to prevent duplicate/ghost nodes
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
    assert code_force == 1
    mock_enroll.assert_not_called()
    captured_force = capsys.readouterr()
    assert "Automatic re-enrollment with --force is disabled to prevent duplicate/ghost nodes" in captured_force.err

    # Identity remains intact and was NOT overwritten
    saved = load_identity(tmp_path)
    assert saved is not None
    assert saved.node_id == "existing-node"
    assert saved.node_secret == "secret-old"


@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_enroll_expired_code_surfaces_code_and_message(
    mock_enroll: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 1: Expired enrollment code surfaces authoritative code and message, saves no identity."""
    mock_enroll.side_effect = EnrollmentError(
        "Enrollment code has expired.",
        code="NODE_ENROLLMENT_CODE_EXPIRED",
        status_code=400,
    )

    code = main(
        [
            "enroll",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--code",
            "expired-token",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "Enrollment failed:" in captured.err
    assert "code=NODE_ENROLLMENT_CODE_EXPIRED" in captured.err
    assert "message=Enrollment code has expired." in captured.err
    assert "status 400" not in captured.err  # Not just an unhelpful status 400

    # No identity file written
    assert load_identity(tmp_path) is None


@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_enroll_invalid_code_surfaces_code_and_message(
    mock_enroll: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 2: Invalid enrollment code surfaces code and message, saves no identity."""
    mock_enroll.side_effect = EnrollmentError(
        "Enrollment code is invalid.",
        code="NODE_ENROLLMENT_CODE_INVALID",
        status_code=400,
    )

    code = main(
        [
            "enroll",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--code",
            "invalid-token",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "code=NODE_ENROLLMENT_CODE_INVALID" in captured.err
    assert "message=Enrollment code is invalid." in captured.err
    assert load_identity(tmp_path) is None


@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_enroll_already_used_code_surfaces_reason(
    mock_enroll: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 3: Already consumed enrollment code surfaces clear reason, saves no identity."""
    mock_enroll.side_effect = EnrollmentError(
        "Enrollment code has already been used.",
        code="NODE_ENROLLMENT_CODE_INVALID",
        status_code=400,
    )

    code = main(
        [
            "enroll",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--code",
            "already-used-token",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "code=NODE_ENROLLMENT_CODE_INVALID" in captured.err
    assert "message=Enrollment code has already been used." in captured.err
    assert load_identity(tmp_path) is None


@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_enroll_non_json_error_fallback(
    mock_enroll: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Test 4: Non-JSON / malformed HTTP error body falls back gracefully without crashing."""
    mock_enroll.side_effect = EnrollmentError(
        "HTTP request failed with status 502: Bad Gateway: upstream server unavailable",
        code=None,
        status_code=502,
    )

    code = main(
        [
            "enroll",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--code",
            "valid-token",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert "Enrollment failed:" in captured.err
    assert "HTTP request failed with status 502" in captured.err
    assert "Bad Gateway" in captured.err
    assert load_identity(tmp_path) is None
