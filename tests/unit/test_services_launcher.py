"""Unit tests for services/services.py command and configuration builder."""

from pathlib import Path
import pytest

from services.services import command


@pytest.fixture
def dummy_manifests(tmp_path: Path) -> Path:
    manifest_dir = tmp_path / "manifests"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    return manifest_dir


def test_runtime_command_default_ports_and_hosts(dummy_manifests: Path) -> None:
    env = {
        "RUNTIME_HOST": "192.168.0.7",
        "DATASET_MANAGER_URL": "http://127.0.0.1:9200",
    }
    cmd = command("runtime", env, dummy_manifests, [])
    assert "--host" in cmd
    host_idx = cmd.index("--host")
    assert cmd[host_idx + 1] == "192.168.0.7"

    assert "--port" in cmd
    port_idx = cmd.index("--port")
    assert cmd[port_idx + 1] == "9000"

    assert "--management-port" in cmd
    mgmt_idx = cmd.index("--management-port")
    assert cmd[mgmt_idx + 1] == "9001"


def test_runtime_command_bind_host_override(dummy_manifests: Path) -> None:
    env = {
        "RUNTIME_HOST": "192.168.0.7",
        "RUNTIME_BIND_HOST": "0.0.0.0",
        "DATASET_MANAGER_URL": "http://127.0.0.1:9200",
    }
    cmd = command("runtime", env, dummy_manifests, [])
    host_idx = cmd.index("--host")
    assert cmd[host_idx + 1] == "0.0.0.0"


def test_runtime_command_cli_extra_no_duplicates(dummy_manifests: Path) -> None:
    env = {
        "RUNTIME_HOST": "192.168.0.7",
        "DATASET_MANAGER_URL": "http://127.0.0.1:9200",
    }
    cmd = command("runtime", env, dummy_manifests, ["--host", "10.0.0.1", "--port", "9999"])
    assert cmd.count("--host") == 1
    assert cmd[cmd.index("--host") + 1] == "10.0.0.1"
    assert cmd.count("--port") == 1
    assert cmd[cmd.index("--port") + 1] == "9999"


def test_backend_command_args(dummy_manifests: Path) -> None:
    env = {
        "BACKEND_HOST": "192.168.0.7",
        "BACKEND_PORT": "8080",
    }
    cmd = command("backend", env, dummy_manifests, [])
    assert "--host" in cmd
    assert cmd[cmd.index("--host") + 1] == "192.168.0.7"
    assert "--port" in cmd
    assert cmd[cmd.index("--port") + 1] == "8080"


def test_node_agent_auto_backend_url(dummy_manifests: Path) -> None:
    # Derives from BACKEND_HOST and BACKEND_PORT
    env = {
        "BACKEND_HOST": "192.168.0.7",
        "BACKEND_PORT": "8000",
    }
    cmd = command("agent", env, dummy_manifests, [])
    assert "--backend-url" in cmd
    assert cmd[cmd.index("--backend-url") + 1] == "http://192.168.0.7:8000"


def test_node_agent_wildcard_host_fallback(dummy_manifests: Path) -> None:
    # 0.0.0.0 falls back to RUNTIME_ADVERTISED_HOST or 127.0.0.1
    env1 = {
        "BACKEND_HOST": "0.0.0.0",
        "BACKEND_PORT": "8000",
        "RUNTIME_ADVERTISED_HOST": "192.168.0.7",
    }
    cmd1 = command("agent", env1, dummy_manifests, [])
    assert cmd1[cmd1.index("--backend-url") + 1] == "http://192.168.0.7:8000"

    env2 = {
        "BACKEND_HOST": "0.0.0.0",
        "BACKEND_PORT": "8000",
    }
    cmd2 = command("agent", env2, dummy_manifests, [])
    assert cmd2[cmd2.index("--backend-url") + 1] == "http://127.0.0.1:8000"


def test_node_agent_respects_explicit_backend_url(dummy_manifests: Path) -> None:
    env = {
        "BACKEND_HOST": "192.168.0.7",
        "BACKEND_PORT": "8000",
    }
    cmd = command("agent", env, dummy_manifests, ["--backend-url", "http://custom-server:9000"])
    assert cmd.count("--backend-url") == 1
    assert cmd[cmd.index("--backend-url") + 1] == "http://custom-server:9000"

