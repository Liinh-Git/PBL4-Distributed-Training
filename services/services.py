"""Portable process launch helpers; jobs and training are controlled through WebUI."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Auto-reexec inside project .venv if invoked with an external python interpreter
_venv_python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
if _venv_python.is_file() and Path(sys.executable).resolve() != _venv_python.resolve():
    raise SystemExit(subprocess.call([str(_venv_python), *sys.argv]))

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def environment() -> dict[str, str]:
    from dotenv import dotenv_values

    env = {**os.environ}
    for key, value in dotenv_values(ROOT / ".env").items():
        if value is not None:
            env.setdefault(key, value)
    pythonpath = env.get("PYTHONPATH", "")
    src_str = str(SRC)
    if src_str not in pythonpath.split(os.pathsep):
        env["PYTHONPATH"] = f"{src_str}{os.pathsep}{pythonpath}" if pythonpath else src_str
    return env


def prepare_manifests(env: dict[str, str]) -> Path:
    from pbl4.common.model_profiles import MODEL_PROFILES

    directory = Path(env.get("PBL4_STATE_DIR", str(ROOT / "var"))) / "manifests"
    for model_id in MODEL_PROFILES:
        path = directory / f"{model_id}.json"
        # Derive from installed model definitions so stale manifests cannot survive an update.
        subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts/derive_parameter_manifest.py"),
                "--model-id",
                model_id,
                "--output",
                str(path),
            ],
            cwd=ROOT,
            env=env,
            check=True,
            stdout=subprocess.DEVNULL,
        )
        manifest = json.loads(path.read_text(encoding="utf-8"))
        env[f"PARAMETER_MANIFEST_HASH_{model_id.upper()}"] = manifest["parameter_manifest_hash"]
    return directory


def command(service: str, env: dict[str, str], manifests: Path, extra: list[str]) -> list[str]:
    if service == "runtime":
        return [
            sys.executable,
            "-m",
            "pbl4.runtime.entrypoint",
            "--host",
            env.get("RUNTIME_BIND_HOST", "127.0.0.1"),
            "--port",
            env.get("RUNTIME_PORT", "5000"),
            "--management-port",
            env.get("RUNTIME_MANAGEMENT_PORT", "7443"),
            "--dataset-manager-url",
            env["DATASET_MANAGER_URL"],
            "--checkpoint-dir",
            str(Path(env.get("PBL4_STATE_DIR", str(ROOT / "var"))) / "checkpoints"),
            "--manifest-dir",
            str(manifests),
            *extra,
        ]
    if service == "backend":
        return [sys.executable, "-m", "pbl4.management_backend.entrypoint", "--http", "h11", *extra]
    return [sys.executable, "-m", "pbl4.node_agent.entrypoint", "start", *extra]


def main(service: str = "all") -> None:
    os.chdir(ROOT)
    env = environment()
    if service != "all":
        manifests = prepare_manifests(env) if service != "agent" else ROOT / "var/manifests"
        raise SystemExit(
            subprocess.call(command(service, env, manifests, sys.argv[1:]), env=env, cwd=ROOT)
        )

    parser = argparse.ArgumentParser(
        description="Start local PBL4 infrastructure (Runtime, Backend, WebUI)."
    )
    parser.add_argument("--web-port", type=int, default=3000)
    args = parser.parse_args()
    # All-in-one mode always uses loopback; no machine-specific LAN address is needed.
    env.update(
        RUNTIME_HOST="127.0.0.1",
        RUNTIME_BIND_HOST="127.0.0.1",
        RUNTIME_ADVERTISED_HOST="127.0.0.1",
        BACKEND_HOST="127.0.0.1",
    )
    env.setdefault("RUNTIME_PORT", "5000")
    env.setdefault("RUNTIME_MANAGEMENT_PORT", "7443")
    backend_port = int(env.get("BACKEND_PORT") or "8000")
    ports = [
        int(env["RUNTIME_PORT"]),
        int(env["RUNTIME_MANAGEMENT_PORT"]),
        backend_port,
        args.web_port,
    ]
    if len(set(ports)) != len(ports):
        parser.error("Service ports must be distinct")
    for port in ports:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                parser.error(f"Port {port} is already in use. Stop the previous service first.")
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm or not (ROOT / "web/node_modules").exists():
        parser.error("Install Node.js and run npm ci in web/ first")
    if (
        not env.get("DATABASE_URL")
        or not env.get("PBL4_WORKER_ADMISSION_SECRET")
        or not env.get("DATASET_MANAGER_URL")
    ):
        parser.error(
            "Configure DATABASE_URL, DATASET_MANAGER_URL and PBL4_WORKER_ADMISSION_SECRET in .env"
        )
    env["CORS_ORIGINS"] = json.dumps(
        [f"http://127.0.0.1:{args.web_port}", f"http://localhost:{args.web_port}"]
    )
    env["VITE_API_BASE_URL"] = f"http://127.0.0.1:{backend_port}"
    env["VITE_WS_BASE_URL"] = f"ws://127.0.0.1:{backend_port}"
    manifests = prepare_manifests(env)
    state_root = Path(env.get("PBL4_STATE_DIR", str(ROOT / "var"))).resolve()
    logs = state_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    children: list[subprocess.Popen] = []
    handles = []

    def start(name: str, cmd: list[str], cwd: Path = ROOT) -> None:
        handle = (logs / f"{name}.log").open("ab")
        handles.append(handle)
        children.append(
            subprocess.Popen(cmd, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT)
        )
        print(f"Started {name}; log: {logs / (name + '.log')}", flush=True)

    try:
        start("runtime", command("runtime", env, manifests, []))
        start("backend", command("backend", env, manifests, []))
        deadline = time.monotonic() + 60
        while True:
            if any(p.poll() is not None for p in children):
                raise RuntimeError("A service exited during startup; inspect var/logs")
            try:
                with socket.create_connection(("127.0.0.1", backend_port), timeout=1):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "Backend startup timed out; inspect var/logs/backend.log"
                    ) from None
                time.sleep(0.5)

        start(
            "web",
            [
                npm,
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                str(args.web_port),
                "--strictPort",
            ],
            ROOT / "web",
        )
        print(
            f"Open http://127.0.0.1:{args.web_port}; create jobs in WebUI.\n"
            "Start Node Agents in separate terminals using: python services/node-agent.py\n"
            "Ctrl+C stops services.",
            flush=True,
        )
        while all(p.poll() is None for p in children):
            time.sleep(1)
        raise RuntimeError("A service stopped; inspect var/logs")
    except KeyboardInterrupt:
        print("Stopping local services; dataset caches and node identities are retained.")
    finally:
        # Include child workers and npm's Vite child, but never touch unrelated processes.
        import psutil

        descendants = []
        for child in children:
            if child.poll() is None:
                try:
                    parent = psutil.Process(child.pid)
                    descendants.extend(parent.children(recursive=True))
                    descendants.append(parent)
                except psutil.NoSuchProcess:
                    pass
        for process in descendants:
            with contextlib.suppress(psutil.NoSuchProcess):
                process.terminate()
        _, alive = psutil.wait_procs(descendants, timeout=5)
        for process in alive:
            with contextlib.suppress(psutil.NoSuchProcess):
                process.kill()
        for handle in handles:
            handle.close()
