"""Unit tests for pbl4-agent CLI entrypoint (start, status).

Auto-enrollment on start and removal of explicit enroll command.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pbl4.node_agent.enrollment import EnrollmentConnectionError, EnrollmentError
from pbl4.node_agent.entrypoint import main
from pbl4.node_agent.identity import NodeIdentity, load_identity, save_identity


@pytest.fixture(autouse=True)
def static_capabilities_without_hardware_probe(monkeypatch):
    monkeypatch.setattr("pbl4.node_agent.entrypoint.collect_static_capabilities", lambda: {})


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
    assert "auto-enroll" in captured.out.lower()
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


def test_cli_enroll_subcommand_removed(capsys: pytest.CaptureFixture[str]) -> None:
    """Verifies that 'pbl4-agent enroll' subcommand has been completely removed."""
    with pytest.raises(SystemExit) as exc_info:
        main(["enroll", "--backend-url", "http://127.0.0.1:8000"])
    assert exc_info.value.code != 0
    captured = capsys.readouterr()
    assert (
        "invalid choice" in captured.err
        or "unrecognized" in captured.err
        or "error" in captured.err.lower()
    )


@patch("pbl4.node_agent.entrypoint.NodeAgentClient")
@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_start_auto_enroll_success(
    mock_enroll: MagicMock,
    mock_client_cls: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When node identity does not exist, start automatically calls enroll and persists identity."""
    mock_enroll.return_value = NodeIdentity(node_id="node-auto-123", node_secret="secret-auto-456")
    mock_client_instance = MagicMock()
    mock_client_instance.start = AsyncMock()
    mock_client_cls.return_value = mock_client_instance

    code = main(
        [
            "start",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    mock_enroll.assert_called_once()
    saved = load_identity(tmp_path)
    assert saved is not None
    assert saved.node_id == "node-auto-123"
    assert saved.node_secret == "secret-auto-456"

    mock_client_cls.assert_called_once()
    _, kwargs = mock_client_cls.call_args
    assert kwargs["identity"].node_id == "node-auto-123"


@patch("pbl4.node_agent.entrypoint.NodeAgentClient")
@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_start_existing_identity_skips_enroll(
    mock_enroll: MagicMock,
    mock_client_cls: MagicMock,
    tmp_path: Path,
) -> None:
    """When node identity already exists, start reuses it and never calls enroll."""
    save_identity(tmp_path, NodeIdentity(node_id="existing-node-77", node_secret="secret-77"))
    mock_client_instance = MagicMock()
    mock_client_instance.start = AsyncMock()
    mock_client_cls.return_value = mock_client_instance

    code = main(
        [
            "start",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 0
    mock_enroll.assert_not_called()
    mock_client_cls.assert_called_once()
    _, kwargs = mock_client_cls.call_args
    assert kwargs["identity"].node_id == "existing-node-77"


@patch("pbl4.node_agent.entrypoint.enroll")
def test_cli_start_auto_enroll_failure(
    mock_enroll: MagicMock,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When auto-enrollment fails, start exits with code 1 and writes no identity."""
    mock_enroll.side_effect = EnrollmentError("Backend unreachable", code="CONNECTION_FAILED")

    code = main(
        [
            "start",
            "--backend-url",
            "http://127.0.0.1:8000",
            "--var-dir",
            str(tmp_path),
        ]
    )
    assert code == 1
    captured = capsys.readouterr()
    assert (
        "Auto-enrollment failed:" in captured.err or "Error: Auto-enrollment failed" in captured.err
    )
    assert load_identity(tmp_path) is None


@patch("pbl4.node_agent.entrypoint.time.sleep")
@patch("pbl4.node_agent.entrypoint.NodeAgentClient")
@patch("pbl4.node_agent.entrypoint.enroll")
def test_start_before_backend_retries_then_persists_one_identity(
    mock_enroll, mock_client, mock_sleep, tmp_path
):
    mock_enroll.side_effect = [
        EnrollmentConnectionError("unavailable"),
        NodeIdentity("node-retry", "private"),
    ]
    mock_client.return_value.start = AsyncMock()
    assert (
        main(["start", "--backend-url", "http://127.0.0.1:8000", "--var-dir", str(tmp_path)]) == 0
    )
    assert mock_enroll.call_count == 2
    mock_sleep.assert_called_once_with(1.0)
    assert load_identity(tmp_path).node_id == "node-retry"


def test_cli_start_duplicate_var_dir_fails_fast(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """When a var-dir is already locked by another agent, start fails fast with exit code 1."""
    from pbl4.node_agent.dir_lock import NodeAgentDirectoryLock

    lock = NodeAgentDirectoryLock(tmp_path)
    assert lock.acquire() is True
    try:
        code = main(
            [
                "start",
                "--backend-url",
                "http://127.0.0.1:8000",
                "--var-dir",
                str(tmp_path),
            ]
        )
        assert code == 1
        captured = capsys.readouterr()
        assert "already in use by another Node Agent" in captured.err
    finally:
        lock.release()
