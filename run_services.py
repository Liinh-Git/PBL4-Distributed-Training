"""Multi-machine PBL4 launcher.

Edit the CONFIG block below for the role of THIS machine, then run:

    python run_services.py            # start the selected services
    python run_services.py --dry-run  # print effective config without starting anything

Values filled in CONFIG temporarily override the .env files for this run only;
the files on disk are never modified. Empty strings mean "keep the .env value".
"""

from __future__ import annotations

import argparse
import contextlib
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.services import command, environment, prepare_manifests  # noqa: E402

# ═══════════════════════════ CONFIG — edit per machine ═══════════════════════════

# Which services to start on this machine
START_RUNTIME = True
START_BACKEND = True
START_NODE_AGENT = True
START_WEB = True

# Runtime (Parameter Server)
RUNTIME_BIND_HOST = "127.0.0.1"  # listen address; 0.0.0.0 accepts remote workers
RUNTIME_HOST = "127.0.0.1"  # address Backend uses to reach Runtime (MCP/1 + default DTP advertise)
RUNTIME_ADVERTISED_HOST = ""  # ps_host handed to workers; empty = RUNTIME_HOST
RUNTIME_PORT = 5000
RUNTIME_MANAGEMENT_PORT = 7443

# Management Backend
BACKEND_BIND_HOST = "127.0.0.1"  # listen address; 0.0.0.0 accepts remote agents/WebUI
BACKEND_PORT = 8000
BACKEND_URL = ""  # public origin of the Backend (e.g. http://192.168.1.20:8000); empty = derived

# Dataset Manager
DATASET_MANAGER_URL = ""  # empty = keep the value from .env

# Node Agent
NODE_AGENT_BACKEND_URL = ""  # empty = BACKEND_URL
NODE_AGENT_VAR_DIR = "var/agent"

# WebUI
WEB_BIND_HOST = "127.0.0.1"
WEB_PORT = 3000

# Optional overrides; empty = keep the value from .env
CORS_ORIGINS = ""  # comma-separated origins; WebUI origins are appended when START_WEB is on
DATABASE_URL = ""
PBL4_WORKER_ADMISSION_SECRET = ""

# ═════════════════════════════════════════════════════════════════════════════════

_LOOPBACK_OR_WILDCARD = ("0.0.0.0", "::")


def resolve_backend_url() -> str:
    candidate = NODE_AGENT_BACKEND_URL or BACKEND_URL
    if candidate:
        return candidate.rstrip("/")
    if BACKEND_BIND_HOST in _LOOPBACK_OR_WILDCARD:
        raise SystemExit(
            "BACKEND_BIND_HOST is a wildcard address — fill BACKEND_URL "
            "(or NODE_AGENT_BACKEND_URL) in run_services.py with the address used "
            f"to reach the Backend, e.g. http://<backend-ip>:{BACKEND_PORT}."
        )
    return f"http://{BACKEND_BIND_HOST}:{BACKEND_PORT}"


def web_origins() -> list[str]:
    if WEB_BIND_HOST in _LOOPBACK_OR_WILDCARD:
        hosts = ["127.0.0.1", "localhost"]
    else:
        hosts = [WEB_BIND_HOST, "127.0.0.1", "localhost"]
    return list(dict.fromkeys(f"http://{host}:{WEB_PORT}" for host in hosts))


def build_env() -> dict[str, str]:
    env = environment()
    overrides = {
        "RUNTIME_HOST": RUNTIME_HOST,
        "RUNTIME_BIND_HOST": RUNTIME_BIND_HOST,
        "RUNTIME_PORT": str(RUNTIME_PORT),
        "RUNTIME_MANAGEMENT_PORT": str(RUNTIME_MANAGEMENT_PORT),
        "BACKEND_HOST": BACKEND_BIND_HOST,
        "BACKEND_PORT": str(BACKEND_PORT),
    }
    if RUNTIME_ADVERTISED_HOST:
        overrides["RUNTIME_ADVERTISED_HOST"] = RUNTIME_ADVERTISED_HOST
    if DATASET_MANAGER_URL:
        overrides["DATASET_MANAGER_URL"] = DATASET_MANAGER_URL
    if DATABASE_URL:
        overrides["DATABASE_URL"] = DATABASE_URL
    if PBL4_WORKER_ADMISSION_SECRET:
        overrides["PBL4_WORKER_ADMISSION_SECRET"] = PBL4_WORKER_ADMISSION_SECRET
    cors = CORS_ORIGINS
    if not cors and START_BACKEND and START_WEB:
        existing = [o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip()]
        cors = ",".join(dict.fromkeys([*existing, *web_origins()]))
    if cors:
        overrides["CORS_ORIGINS"] = cors
    env.update(overrides)
    if START_WEB:
        origin = resolve_backend_url()
        scheme, rest = origin.split("://", 1)
        env["VITE_API_BASE_URL"] = origin
        env["VITE_WS_BASE_URL"] = ("wss" if scheme == "https" else "ws") + "://" + rest
    return env


def runtime_command(env: dict[str, str], manifests: Path, extra: list[str]) -> list[str]:
    return command("runtime", env, manifests, extra)


def backend_command(extra: list[str]) -> list[str]:
    return command("backend", {}, Path("var/manifests"), extra)


def agent_command(env: dict[str, str], extra: list[str]) -> list[str]:
    agent_args = [
        "--backend-url",
        resolve_backend_url(),
        "--var-dir",
        NODE_AGENT_VAR_DIR,
        *extra,
    ]
    return command("agent", env, Path("var/manifests"), agent_args)


def web_command(npm: str) -> list[str]:
    return [
        npm,
        "run",
        "dev",
        "--",
        "--host",
        WEB_BIND_HOST,
        "--port",
        str(WEB_PORT),
        "--strictPort",
    ]


def find_npm() -> str:
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    if not npm or not (ROOT / "web/node_modules").exists():
        raise SystemExit("Install Node.js and run npm ci in web/ first")
    return npm


def check_ports(ports: list[int]) -> None:
    if len(set(ports)) != len(ports):
        raise SystemExit("Service ports must be distinct.")
    for port in ports:
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                raise SystemExit(
                    f"Port {port} is already in use. Stop the previous service first."
                ) from None


def wait_for_backend() -> None:
    host = "127.0.0.1" if BACKEND_BIND_HOST in _LOOPBACK_OR_WILDCARD else BACKEND_BIND_HOST
    deadline = time.monotonic() + 60
    while True:
        try:
            with socket.create_connection((host, BACKEND_PORT), timeout=1):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "Backend startup timed out; inspect var/logs/backend.log"
                ) from None
            time.sleep(0.5)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Start selected PBL4 services with per-run address overrides from the CONFIG block."
        )
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="print the effective configuration and exit"
    )
    args, extra = parser.parse_known_args()

    os.chdir(ROOT)
    flags = {
        "runtime": START_RUNTIME,
        "backend": START_BACKEND,
        "node-agent": START_NODE_AGENT,
        "web": START_WEB,
    }
    started = [name for name, enabled in flags.items() if enabled]
    if not started:
        raise SystemExit(
            "Set at least one START_* flag to True in the CONFIG block of run_services.py."
        )
    if extra and len([name for name in started if name != "web"]) != 1:
        print(
            f"Ignoring extra arguments {extra!r}; "
            "pass them only when a single Python service is started.",
            file=sys.stderr,
        )
        extra = []

    env = build_env()
    if START_RUNTIME or START_BACKEND:
        if not env.get("DATASET_MANAGER_URL"):
            raise SystemExit(
                "DATASET_MANAGER_URL is required; set it in .env or in run_services.py."
            )
        if not env.get("PBL4_WORKER_ADMISSION_SECRET") and "--allow-unmanaged-workers" not in extra:
            raise SystemExit(
                "PBL4_WORKER_ADMISSION_SECRET is required; set it in .env or in run_services.py, "
                "or pass --allow-unmanaged-workers to the runtime."
            )
    if START_BACKEND and not env.get("DATABASE_URL"):
        raise SystemExit(
            "DATABASE_URL is required for the Backend; set it in .env or in run_services.py."
        )

    manifests = ROOT / "var/manifests"
    commands: dict[str, list[str]] = {}
    if START_RUNTIME:
        commands["runtime"] = runtime_command(env, manifests, extra)
    if START_BACKEND:
        commands["backend"] = backend_command(extra)
    if START_NODE_AGENT:
        commands["node-agent"] = agent_command(env, extra)
    npm: str | None = None
    if START_WEB:
        npm = find_npm()
        commands["web"] = web_command(npm)

    ports: list[int] = []
    if START_RUNTIME:
        ports += [RUNTIME_PORT, RUNTIME_MANAGEMENT_PORT]
    if START_BACKEND:
        ports.append(BACKEND_PORT)
    if START_WEB:
        ports.append(WEB_PORT)

    if args.dry_run:
        print("Services:", ", ".join(started))
        if START_RUNTIME:
            print(
                f"  runtime: bind {RUNTIME_BIND_HOST}:{RUNTIME_PORT} "
                f"(management {RUNTIME_MANAGEMENT_PORT}, "
                f"advertised {RUNTIME_ADVERTISED_HOST or RUNTIME_HOST}:{RUNTIME_PORT})"
            )
        if START_BACKEND:
            print(f"  backend: bind {BACKEND_BIND_HOST}:{BACKEND_PORT}")
        if START_NODE_AGENT:
            print(f"  node-agent: backend {resolve_backend_url()} (var-dir {NODE_AGENT_VAR_DIR})")
        if START_WEB:
            print(f"  web: {web_origins()[0]} -> api {env['VITE_API_BASE_URL']}")
        print("Env overrides:")
        for key in sorted(
            k
            for k in env
            if k
            in {
                "RUNTIME_HOST",
                "RUNTIME_BIND_HOST",
                "RUNTIME_ADVERTISED_HOST",
                "RUNTIME_PORT",
                "RUNTIME_MANAGEMENT_PORT",
                "BACKEND_HOST",
                "BACKEND_PORT",
                "DATASET_MANAGER_URL",
                "DATABASE_URL",
                "PBL4_WORKER_ADMISSION_SECRET",
                "CORS_ORIGINS",
                "VITE_API_BASE_URL",
                "VITE_WS_BASE_URL",
            }
            and (
                k
                in {
                    "RUNTIME_HOST",
                    "RUNTIME_BIND_HOST",
                    "RUNTIME_PORT",
                    "RUNTIME_MANAGEMENT_PORT",
                    "BACKEND_HOST",
                    "BACKEND_PORT",
                }
                or env.get(k)
            )
        ):
            value = "***" if "SECRET" in key or key == "DATABASE_URL" else env[key]
            print(f"  {key}={value}")
        for name, argv in commands.items():
            print(f"Command [{name}]: {' '.join(argv)}")
        return

    check_ports(ports)
    manifests = prepare_manifests(env) if START_RUNTIME or START_BACKEND else manifests

    print(f"Starting: {', '.join(started)}", flush=True)
    if START_RUNTIME:
        print(
            f"  runtime: bind {RUNTIME_BIND_HOST}:{RUNTIME_PORT} "
            f"(management {RUNTIME_MANAGEMENT_PORT}, "
            f"advertised {RUNTIME_ADVERTISED_HOST or RUNTIME_HOST}:{RUNTIME_PORT})",
            flush=True,
        )
    if START_BACKEND:
        print(f"  backend: bind {BACKEND_BIND_HOST}:{BACKEND_PORT}", flush=True)
    if START_NODE_AGENT:
        print(
            f"  node-agent: backend {resolve_backend_url()} (var-dir {NODE_AGENT_VAR_DIR})",
            flush=True,
        )
    if START_WEB:
        print(f"  web: {web_origins()[0]}", flush=True)

    state_root = Path(env.get("PBL4_STATE_DIR", str(ROOT / "var"))).resolve()
    logs = state_root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    children: list[subprocess.Popen] = []
    handles = []

    def start(name: str, argv: list[str], cwd: Path = ROOT) -> None:
        handle = (logs / f"{name}.log").open("ab")
        handles.append(handle)
        children.append(
            subprocess.Popen(argv, cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT)
        )
        print(f"Started {name}; log: {logs / (name + '.log')}", flush=True)

    try:
        if START_RUNTIME:
            start("runtime", commands["runtime"])
        if START_BACKEND:
            start("backend", commands["backend"])
        if START_BACKEND and START_NODE_AGENT:
            wait_for_backend()
        if START_NODE_AGENT:
            start("node-agent", commands["node-agent"])
        if START_WEB:
            start("web", commands["web"], ROOT / "web")
            print(
                f"Open {web_origins()[0]}; create jobs in WebUI. Ctrl+C stops services.",
                flush=True,
            )
        else:
            print("Ctrl+C stops services.", flush=True)
        while all(p.poll() is None for p in children):
            time.sleep(1)
        raise RuntimeError("A service stopped; inspect var/logs")
    except KeyboardInterrupt:
        print("Stopping services; dataset caches and node identities are retained.")
    finally:
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
