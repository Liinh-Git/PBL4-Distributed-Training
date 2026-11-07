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
        cmd = [sys.executable, "-m", "pbl4.runtime.entrypoint"]
        if not any(arg == "--host" or arg.startswith("--host=") for arg in extra):
            host = env.get("RUNTIME_BIND_HOST") or env.get("RUNTIME_HOST", "127.0.0.1")
            cmd.extend(["--host", host])
        if not any(arg == "--port" or arg.startswith("--port=") for arg in extra):
            cmd.extend(["--port", env.get("RUNTIME_PORT", "9000")])
        if not any(arg == "--management-port" or arg.startswith("--management-port=") for arg in extra):
            cmd.extend(["--management-port", env.get("RUNTIME_MANAGEMENT_PORT", "9001")])
        cmd.extend(
            [
                "--dataset-manager-url",
                env["DATASET_MANAGER_URL"],
                "--checkpoint-dir",
                str(Path(env.get("PBL4_STATE_DIR", str(ROOT / "var"))) / "checkpoints"),
                "--manifest-dir",
                str(manifests),
                *extra,
            ]
        )
        return cmd
    if service == "backend":
        cmd = [sys.executable, "-m", "pbl4.management_backend.entrypoint", "--http", "h11"]
        bind_host = env.get("BACKEND_HOST")
        if bind_host and not any(arg == "--host" or arg.startswith("--host=") for arg in extra):
            cmd.extend(["--host", bind_host])
        port = env.get("BACKEND_PORT")
        if port and not any(arg == "--port" or arg.startswith("--port=") for arg in extra):
            cmd.extend(["--port", str(port)])
        cmd.extend(extra)
        return cmd
    if service == "agent":
        cmd = [sys.executable, "-m", "pbl4.node_agent.entrypoint", "start"]
        if not any(arg == "--backend-url" or arg.startswith("--backend-url=") for arg in extra):
            backend_host = env.get("BACKEND_HOST", "127.0.0.1")
            if backend_host in ("0.0.0.0", "::"):
                backend_host = env.get("RUNTIME_ADVERTISED_HOST") or "127.0.0.1"
            backend_port = env.get("BACKEND_PORT", "8000")
            cmd.extend(["--backend-url", f"http://{backend_host}:{backend_port}"])
        cmd.extend(extra)
        return cmd
    raise ValueError(f"Unknown service: {service}")


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
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Host interface/IP for services (defaults to .env or 127.0.0.1)",
    )
    parser.add_argument("--web-port", type=int, default=3000)
    args = parser.parse_args()

    if args.host:
        env["RUNTIME_HOST"] = args.host
        env["RUNTIME_BIND_HOST"] = args.host
        env["RUNTIME_ADVERTISED_HOST"] = args.host
        env["BACKEND_HOST"] = args.host
    else:
        env.setdefault("RUNTIME_HOST", "127.0.0.1")
        env.setdefault("RUNTIME_BIND_HOST", env["RUNTIME_HOST"])
        env.setdefault("RUNTIME_ADVERTISED_HOST", env["RUNTIME_HOST"])
        env.setdefault("BACKEND_HOST", "127.0.0.1")

    env.setdefault("RUNTIME_PORT", "9000")
    env.setdefault("RUNTIME_MANAGEMENT_PORT", "9001")
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
                probe.bind(("", port))
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

    backend_host = env.get("BACKEND_HOST", "127.0.0.1")
    public_backend_host = (
        env.get("RUNTIME_ADVERTISED_HOST")
        or (backend_host if backend_host not in ("0.0.0.0", "::") else "127.0.0.1")
    )
    backend_origin = f"http://{public_backend_host}:{backend_port}"
    env["VITE_API_BASE_URL"] = backend_origin
    env["VITE_WS_BASE_URL"] = f"ws://{public_backend_host}:{backend_port}"

    cors_origins = {
        f"http://127.0.0.1:{args.web_port}",
        f"http://localhost:{args.web_port}",
    }
    if public_backend_host not in ("127.0.0.1", "localhost"):
        cors_origins.add(f"http://{public_backend_host}:{args.web_port}")
    extra_cors = env.get("CORS_ORIGINS", "")
    if extra_cors:
        try:
            parsed = json.loads(extra_cors)
            if isinstance(parsed, list):
                cors_origins.update(parsed)
        except (json.JSONDecodeError, TypeError):
            cors_origins.update(o.strip() for o in extra_cors.split(",") if o.strip())
    env["CORS_ORIGINS"] = json.dumps(sorted(cors_origins))

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
        connect_host = "127.0.0.1" if backend_host in ("0.0.0.0", "::") else backend_host
        while True:
            if any(p.poll() is not None for p in children):
                raise RuntimeError("A service exited during startup; inspect var/logs")
            try:
                with socket.create_connection((connect_host, backend_port), timeout=1):
                    break
            except OSError:
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
                "0.0.0.0",
                "--port",
                str(args.web_port),
                "--strictPort",
            ],
            ROOT / "web",
        )
        print(
            f"PBL4 services running:\n"
            f"  - WebUI (Local):   http://127.0.0.1:{args.web_port}\n"
            + (
                f"  - WebUI (Network): http://{public_backend_host}:{args.web_port}\n"
                if public_backend_host not in ("127.0.0.1", "localhost")
                else ""
            )
            + f"  - Backend API:     {backend_origin}\n"
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


if __name__ == "__main__":
    main()
