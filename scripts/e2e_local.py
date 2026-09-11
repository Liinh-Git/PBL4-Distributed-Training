"""Black-box local orchestration for E2E-HAPPY-01.

This script deliberately does not import Runtime, ParameterServer, Coordinator,
TrainingLoop, or any other training implementation.  It starts console processes,
uses public HTTP APIs, and validates persisted/public evidence plus checkpoint bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


@dataclass
class Child:
    name: str
    process: subprocess.Popen[bytes]
    stream: Any
    log_path: Path

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.stream.close()


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        if bool(args.reuse_build_id) != bool(args.reuse_dataset_id):
            raise ValueError("--reuse-build-id and --reuse-dataset-id must be supplied together")
        if args.reuse_build_id and not args.reuse_runtime_data:
            raise ValueError("A reused build requires its reusable PostgreSQL/runtime data")
        if args.smoke_steps < 0:
            raise ValueError("--smoke-steps cannot be negative")
        self.args = args
        self.repo = Path(__file__).resolve().parents[1]
        self.started_at = time.monotonic()
        run_id = args.run_id or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = run_id
        self.artifacts = (self.repo / args.artifact_root / run_id).resolve()
        self.artifacts.mkdir(parents=True, exist_ok=False)
        self.logs = self.artifacts / "logs"
        self.logs.mkdir()
        if args.reuse_runtime_data:
            self.runtime_data = Path(args.reuse_runtime_data).resolve()
            if not self.runtime_data.is_dir():
                raise ValueError("--reuse-runtime-data must name an existing run directory")
        else:
            self.runtime_data = (self.repo / ".var" / "e2e" / run_id).resolve()
            self.runtime_data.mkdir(parents=True, exist_ok=False)
        self.children: list[Child] = []
        self.evidence_path = self.artifacts / "api-evidence.jsonl"
        self.driver_log = self.artifacts / "driver.log"
        self.result: dict[str, Any] = {
            "case": "E2E-HAPPY-01",
            "run_id": run_id,
            "started_at": _now(),
            "batch_size": args.batch_size,
            "ports": {},
            "failures": [],
        }
        self.backend_port = args.backend_port or _free_port()
        self.dataset_port = args.dataset_port or _free_port()
        self.management_port = args.management_port or _free_port()
        self.dtp_port = args.dtp_port or _free_port()
        self.postgres_port = args.postgres_port or _free_port()
        self.result["ports"] = {
            "postgres": self.postgres_port,
            "dataset_manager": self.dataset_port,
            "backend": self.backend_port,
            "runtime_mcp": self.management_port,
            "runtime_dtp": self.dtp_port,
        }
        self.base_url = f"http://127.0.0.1:{self.backend_port}"
        self.database_url = args.database_url
        self.ephemeral_postgres = not bool(self.database_url)
        self._controlled_abort = False

    def log(self, message: str) -> None:
        line = f"{_now()} {message}"
        print(line, flush=True)
        with self.driver_log.open("a", encoding="utf-8") as stream:
            stream.write(line + "\n")

    def start_child(
        self, name: str, command: list[str], env: dict[str, str] | None = None
    ) -> Child:
        log_path = self.logs / f"{name}.log"
        stream = log_path.open("wb")
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=self.repo,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        child = Child(name, process, stream, log_path)
        self.children.append(child)
        self.log(f"started {name} pid={process.pid}: {' '.join(command)}")
        return child

    def checked(
        self,
        name: str,
        command: list[str],
        *,
        env: dict[str, str] | None = None,
    ) -> None:
        log_path = self.logs / f"{name}.log"
        with log_path.open("wb") as stream:
            completed = subprocess.run(
                command,
                cwd=self.repo,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if completed.returncode:
            raise RuntimeError(f"{name} failed with exit code {completed.returncode}: {log_path}")
        self.log(f"completed {name}")

    def request(
        self,
        method: str,
        path: str,
        body: object | None = None,
        *,
        idempotency_key: str | None = None,
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        data = _canonical(body) if body is not None else None
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = urllib.request.Request(
            self.base_url + path, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            raise RuntimeError(
                f"{method} {path} returned HTTP {exc.code}: {raw.decode(errors='replace')}"
            ) from exc
        value = json.loads(raw)
        with self.evidence_path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {"at": _now(), "method": method, "path": path, "status": status, "body": value},
                    sort_keys=True,
                    default=str,
                )
                + "\n"
            )
        return value

    def wait_http(self, url: str, timeout: float, description: str) -> None:
        deadline = time.monotonic() + timeout
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(url, timeout=2.0) as response:
                    if response.status == 200:
                        self.log(f"ready: {description}")
                        return
            except Exception as exc:
                last = exc
            time.sleep(0.25)
        raise TimeoutError(f"Timed out waiting for {description}: {last}")

    def wait_value(self, getter, predicate, timeout: float, description: str):
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            self.assert_live()
            last = getter()
            if predicate(last):
                self.log(f"reached: {description}")
                return last
            time.sleep(self.args.poll_interval)
        raise TimeoutError(f"Timed out waiting for {description}; last={last}")

    def assert_live(self) -> None:
        for child in self.children:
            code = child.process.poll()
            if code is not None and (
                not child.name.startswith("worker-") or (code != 0 and not self._controlled_abort)
            ):
                raise RuntimeError(
                    f"Required child {child.name} exited {code}; see {child.log_path}"
                )

    def setup_postgres(self, env: dict[str, str]) -> None:
        if self.database_url:
            self.result["postgres_mode"] = "configured DATABASE_URL"
            return
        bin_dir = self._postgres_bin()
        pgdata = self.runtime_data / "postgres-data"
        if self.args.reuse_runtime_data:
            if not (pgdata / "PG_VERSION").is_file():
                raise RuntimeError("Reusable runtime data has no PostgreSQL cluster")
            self.start_child(
                "postgres",
                [
                    str(bin_dir / "postgres.exe"),
                    "-D",
                    str(pgdata),
                    "-h",
                    "127.0.0.1",
                    "-p",
                    str(self.postgres_port),
                ],
                env,
            )
            self._wait_postgres(bin_dir)
            self.database_url = f"postgresql://postgres@127.0.0.1:{self.postgres_port}/pbl4_e2e"
            self.result["postgres_mode"] = "reused ephemeral PostgreSQL cluster"
            return
        self.checked(
            "postgres-initdb",
            [
                str(bin_dir / "initdb.exe"),
                "-D",
                str(pgdata),
                "-U",
                "postgres",
                "--auth=trust",
                "--encoding=UTF8",
                "--no-locale",
            ],
        )
        self.start_child(
            "postgres",
            [
                str(bin_dir / "postgres.exe"),
                "-D",
                str(pgdata),
                "-h",
                "127.0.0.1",
                "-p",
                str(self.postgres_port),
            ],
            env,
        )
        self._wait_postgres(bin_dir)
        self.checked(
            "postgres-createdb",
            [
                str(bin_dir / "createdb.exe"),
                "-h",
                "127.0.0.1",
                "-p",
                str(self.postgres_port),
                "-U",
                "postgres",
                "pbl4_e2e",
            ],
        )
        self.database_url = f"postgresql://postgres@127.0.0.1:{self.postgres_port}/pbl4_e2e"
        self.result["postgres_mode"] = "ephemeral PostgreSQL 18"

    def _wait_postgres(self, bin_dir: Path) -> None:
        postgres_url = f"postgresql://postgres@127.0.0.1:{self.postgres_port}/postgres"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            probe = subprocess.run(
                [str(bin_dir / "psql.exe"), postgres_url, "-Atc", "SELECT 1"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            if probe.returncode == 0:
                break
            time.sleep(0.25)
        else:
            raise TimeoutError("Ephemeral PostgreSQL did not accept connections")

    def _postgres_bin(self) -> Path:
        candidates = []
        if self.args.postgres_bin:
            candidates.append(Path(self.args.postgres_bin))
        candidates.extend(
            Path(f"C:/Program Files/PostgreSQL/{version}/bin") for version in range(20, 13, -1)
        )
        for candidate in candidates:
            if (candidate / "initdb.exe").is_file() and (candidate / "postgres.exe").is_file():
                return candidate
        raise RuntimeError(
            "PostgreSQL bin directory not found; pass --postgres-bin or DATABASE_URL"
        )

    def run(self) -> dict[str, Any]:
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONPATH"] = str(self.repo / "src")
        cache_archive = (self.repo / ".var" / "cache" / "cifar-10-binary.tar.gz").resolve()
        if cache_archive.is_file():
            env["PBL4_CIFAR10_SOURCE_ARCHIVE"] = str(cache_archive)
        self.setup_postgres(env)
        assert self.database_url is not None
        env["DATABASE_URL"] = self.database_url

        manifest_path = self.artifacts / "parameter-manifest.json"
        self.checked(
            "derive-parameter-manifest",
            [
                sys.executable,
                str(self.repo / "scripts" / "derive_parameter_manifest.py"),
                "--output",
                str(manifest_path),
                "--seed",
                str(self.args.training_seed),
            ],
            env=env,
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        parameter_hash = manifest["parameter_manifest_hash"]
        if (
            _sha256(
                _canonical(
                    {
                        key: value
                        for key, value in manifest.items()
                        if key != "parameter_manifest_hash"
                    }
                )
            )
            != parameter_hash
        ):
            raise AssertionError("Derived Parameter Manifest self-hash mismatch")
        self.result["parameter_manifest_hash"] = parameter_hash
        env["CANONICAL_PARAMETER_MANIFEST_HASH"] = parameter_hash

        self.checked(
            "alembic-upgrade-head", [sys.executable, "-m", "alembic", "upgrade", "head"], env=env
        )
        self.result["migrations"] = "upgrade head succeeded"

        dataset_store = self.runtime_data / "dataset-store"
        dataset_temp = self.runtime_data / "dataset-temp"
        checkpoint_dir = self.artifacts / "checkpoints"
        self.start_child(
            "dataset-manager",
            [
                sys.executable,
                "-m",
                "pbl4.dataset_manager.entrypoint",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.dataset_port),
                "--store-dir",
                str(dataset_store),
                "--temp-dir",
                str(dataset_temp),
                "--public-base-url",
                f"http://127.0.0.1:{self.dataset_port}",
            ],
            env,
        )
        self.wait_http(f"http://127.0.0.1:{self.dataset_port}/healthz", 30, "Dataset Manager")
        self.start_child(
            "runtime",
            [
                sys.executable,
                "-m",
                "pbl4.runtime.entrypoint",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.dtp_port),
                "--management-port",
                str(self.management_port),
                "--dataset-manager-url",
                f"http://127.0.0.1:{self.dataset_port}",
                "--checkpoint-dir",
                str(checkpoint_dir),
                "--parameter-manifest",
                str(manifest_path),
                "--heartbeat-timeout",
                str(self.args.heartbeat_timeout),
            ],
            env,
        )
        backend_env = {
            **env,
            "BACKEND_HOST": "127.0.0.1",
            "BACKEND_PORT": str(self.backend_port),
            "RUNTIME_HOST": "127.0.0.1",
            "RUNTIME_MANAGEMENT_PORT": str(self.management_port),
            "DATASET_MANAGER_HOST": "127.0.0.1",
            "DATASET_MANAGER_PORT": str(self.dataset_port),
            "EXPECTED_WORKERS": "3",
        }
        self.start_child(
            "backend",
            [
                sys.executable,
                "-m",
                "pbl4.management_backend.entrypoint",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.backend_port),
            ],
            backend_env,
        )
        self.wait_http(f"{self.base_url}/api/v1/health", 60, "Management Backend")
        health = self.request("GET", "/api/v1/health")["data"]
        if health["postgres"] != "healthy" or health["dataset_manager"] != "healthy":
            raise AssertionError(f"Management health is degraded: {health}")
        self.wait_value(
            lambda: self.request("GET", "/api/v1/runtime/snapshot")["data"],
            lambda value: not value["stale"] and bool(value["runtime_instance_id"]),
            60,
            "Backend-to-Runtime MCP/1 connection",
        )

        if self.args.reuse_build_id:
            build_id = self.args.reuse_build_id
            dataset = {"dataset_id": self.args.reuse_dataset_id}
        else:
            dataset = self.request(
                "POST",
                "/api/v1/datasets",
                {
                    "name": f"CIFAR-10 E2E {self.run_id}",
                    "task_type": "image_classification",
                    "source_type": "builtin",
                    "source_reference": "cifar10",
                },
                idempotency_key=f"{self.run_id}-dataset",
            )["data"]
            build_start = self.request(
                "POST",
                "/api/v1/dataset-builds",
                {
                    "dataset_id": dataset["dataset_id"],
                    "profile": "CNN_IMAGE_CLASSIFICATION_V1",
                    "batch_size": self.args.batch_size,
                    "partition_seed": self.args.partition_seed,
                },
                idempotency_key=f"{self.run_id}-build",
                timeout=60,
            )["data"]
            build_id = build_start["dataset_build_id"]
        build = self.wait_value(
            lambda: self.request("GET", f"/api/v1/dataset-builds/{build_id}")["data"],
            lambda value: value["state"] in {"READY", "FAILED"},
            self.args.dataset_timeout,
            "Dataset Build READY",
        )
        if build["state"] != "READY":
            raise AssertionError(f"Dataset Build failed: {build}")
        manifest_url = build["manifest_summary"]["artifact_base_url"] + "/manifest.json"
        with urllib.request.urlopen(manifest_url, timeout=30) as response:
            root_bytes = response.read()
        root_manifest = json.loads(root_bytes)
        if _canonical(root_manifest) != root_bytes:
            raise AssertionError("Dataset Manifest is not canonical JSON")
        if _sha256(root_bytes) != build["manifest_summary"]["dataset_manifest_hash"]:
            raise AssertionError("Dataset Manifest hash mismatch")
        if (
            root_manifest["sample_count"] != 50_000
            or root_manifest["shard_count"] != 3
            or len(root_manifest["shards"]) != 3
        ):
            raise AssertionError(
                f"Dataset is not the full real CIFAR-10 training set: {root_manifest}"
            )
        total_steps = int(root_manifest["batch_count_per_shard"])
        self.result["dataset"] = {
            "dataset_id": dataset["dataset_id"],
            "dataset_build_id": build_id,
            "dataset_manifest_hash": build["manifest_summary"]["dataset_manifest_hash"],
            "sample_count": root_manifest["sample_count"],
            "shard_count": root_manifest["shard_count"],
            "batch_count_per_shard": total_steps,
        }

        job = self.request(
            "POST",
            "/api/v1/jobs",
            {
                "display_name": f"E2E-HAPPY-01 {self.run_id}",
                "description": "Real CIFAR-10, three-process-worker Strict BSP acceptance run",
                "requested_contract": {
                    "dataset_build_id": build_id,
                    "model_id": "resnet18_groupnorm",
                    "epochs": 1,
                    "learning_rate": self.args.learning_rate,
                    "training_seed": self.args.training_seed,
                    "training_strategy": "strict_bsp",
                },
            },
            idempotency_key=f"{self.run_id}-job",
        )["data"]
        job_id = job["job_id"]
        validation = self.request("POST", f"/api/v1/jobs/{job_id}/validate")["data"]
        if validation["errors"] or validation["resolved_preview"] is None:
            raise AssertionError(f"Job validation failed: {validation}")
        preview = validation["resolved_preview"]
        if (
            preview["model"]["parameter_manifest_hash"] != parameter_hash
            or preview["synchronization"]["expected_workers"] != 3
        ):
            raise AssertionError("Resolved preview does not contain real model/3-worker identity")
        started = self.request(
            "POST",
            f"/api/v1/jobs/{job_id}/start",
            {"note": "E2E-HAPPY-01"},
            idempotency_key=f"{self.run_id}-start",
        )["data"]
        attempt_id = started["attempt_id"]
        frozen = self.request("GET", f"/api/v1/jobs/{job_id}")["data"]
        if (
            frozen["state"] != "READY"
            or not frozen["contract_hash"]
            or frozen["resolved_contract"]["model"]["parameter_manifest_hash"] != parameter_hash
        ):
            raise AssertionError(f"Job was not canonically frozen by start: {frozen}")
        self.result["job"] = {
            "job_id": job_id,
            "contract_hash": frozen["contract_hash"],
            "attempt_id": attempt_id,
            "execution_mode": started["execution_mode"],
        }

        workers = []
        for index in range(3):
            cache_dir = self.runtime_data / f"worker-{index}-cache"
            workers.append(
                self.start_child(
                    f"worker-{index}",
                    [
                        sys.executable,
                        "-m",
                        "pbl4.worker.entrypoint",
                        "--runtime-host",
                        "127.0.0.1",
                        "--runtime-port",
                        str(self.dtp_port),
                        "--node-label",
                        f"local-worker-process-{index}",
                        "--cache-dir",
                        str(cache_dir),
                        "--initialization-seed",
                        str(self.args.training_seed),
                        "--device",
                        "cpu",
                        "--heartbeat-interval",
                        str(self.args.heartbeat_interval),
                    ],
                    env,
                )
            )

        if self.args.smoke_steps:
            smoke = self.wait_value(
                lambda: self._poll_smoke(attempt_id),
                lambda value: len(value["steps"]) >= self.args.smoke_steps,
                self.args.training_timeout,
                f"at least {self.args.smoke_steps} committed synchronized updates",
            )
            self._controlled_abort = True
            self.request(
                "POST",
                f"/api/v1/attempts/{attempt_id}/abort",
                {"reason": "Black-box smoke proof complete"},
                idempotency_key=f"{self.run_id}-abort",
            )
            final_snapshot = self.wait_value(
                lambda: self._poll_attempt(attempt_id),
                lambda value: value["attempt"]["state"] == "ABORTED",
                120,
                "controlled smoke Attempt ABORTED",
            )
            for worker in workers:
                worker.process.wait(timeout=60)
            committed = len(smoke["steps"])
            self.verify(attempt_id, committed, parameter_hash, checkpoint_dir, is_smoke=True)
            self.result["duration_seconds"] = round(time.monotonic() - self.started_at, 3)
            self.result["finished_at"] = _now()
            self.result["verdict"] = "SMOKE_PASS"
            return self.result

        final_snapshot = self.wait_value(
            lambda: self._poll_attempt(attempt_id),
            lambda value: value["attempt"]["state"] in {"COMPLETED", "FAILED", "ABORTED"},
            self.args.training_timeout,
            "Attempt terminal state",
        )
        if final_snapshot["attempt"]["state"] != "COMPLETED":
            raise AssertionError(f"Attempt did not complete: {final_snapshot}")
        for worker in workers:
            try:
                code = worker.process.wait(timeout=60)
            except subprocess.TimeoutExpired as exc:
                raise AssertionError(f"{worker.name} did not terminate after completion") from exc
            if code != 0:
                raise AssertionError(f"{worker.name} exited {code}; see {worker.log_path}")

        self.verify(attempt_id, total_steps, parameter_hash, checkpoint_dir)
        self.result["final_runtime"] = final_snapshot["runtime"]
        self.result["final_attempt"] = final_snapshot["attempt"]
        self.result["duration_seconds"] = round(time.monotonic() - self.started_at, 3)
        self.result["finished_at"] = _now()
        self.result["verdict"] = "PASS"
        return self.result

    def _poll_attempt(self, attempt_id: str) -> dict[str, Any]:
        runtime = self.request("GET", "/api/v1/runtime/snapshot")["data"]
        attempt = self.request("GET", f"/api/v1/attempts/{attempt_id}")["data"]
        self.log(
            f"progress attempt={attempt['state']} epoch={runtime.get('epoch')} "
            f"ordinal={runtime.get('current_batch_ordinal')} model={runtime.get('model_version')} "
            f"workers={len(runtime.get('workers') or [])}"
        )
        return {"runtime": runtime, "attempt": attempt}

    def _poll_smoke(self, attempt_id: str) -> dict[str, Any]:
        current = self._poll_attempt(attempt_id)
        steps = self.request("GET", f"/api/v1/attempts/{attempt_id}/steps?limit=200")["data"]
        current["steps"] = [item for item in steps if item["state"] == "COMMITTED"]
        return current

    def events(self, attempt_id: str, event_type: str) -> list[dict[str, Any]]:
        value = self.request(
            "GET",
            f"/api/v1/attempts/{attempt_id}/events?event_type={event_type}&limit=200",
        )
        if value["page"].get("next_cursor"):
            raise AssertionError(f"Event evidence for {event_type} exceeded one canonical page")
        return value["data"]

    def verify(
        self,
        attempt_id: str,
        total_steps: int,
        parameter_hash: str,
        checkpoint_root: Path,
        *,
        is_smoke: bool = False,
    ) -> None:
        workers = self.request("GET", f"/api/v1/attempts/{attempt_id}/workers")["data"]
        if len(workers) != 3 or {item["worker_id"] for item in workers} != {0, 1, 2}:
            raise AssertionError(f"Incorrect worker/session projection: {workers}")
        if len({item["session_id"] for item in workers}) != 3:
            raise AssertionError("Worker sessions are not unique")

        all_steps = self.request("GET", f"/api/v1/attempts/{attempt_id}/steps?limit=200")["data"]
        if is_smoke:
            committed_steps = [item for item in all_steps if item["state"] == "COMMITTED"]
            if len(committed_steps) < total_steps:
                raise AssertionError(
                    f"Committed step count below required smoke threshold: "
                    f"expected={total_steps} actual={len(committed_steps)}"
                )
            steps = committed_steps
        else:
            if len(all_steps) != total_steps or any(
                item["state"] != "COMMITTED" for item in all_steps
            ):
                raise AssertionError(
                    f"Persisted step count/state mismatch expected={total_steps} "
                    f"actual={len(all_steps)}"
                )
            steps = all_steps

        ordered_steps = sorted(steps, key=lambda item: item["operation_id"])[:total_steps]
        if [item["input_model_version"] for item in ordered_steps] != list(range(total_steps)):
            raise AssertionError("Input model versions are not contiguous")
        if [item["output_model_version"] for item in ordered_steps] != list(
            range(1, total_steps + 1)
        ):
            raise AssertionError("Exactly-one update/model-version invariant failed")
        details = [
            self.request("GET", f"/api/v1/attempts/{attempt_id}/steps/{item['step_id']}")["data"]
            for item in ordered_steps
        ]
        for detail in details:
            worker_steps = detail["worker_steps"]
            if len(worker_steps) != 3 or {item["worker_id"] for item in worker_steps} != {0, 1, 2}:
                raise AssertionError(f"Step lacks exactly three worker contributions: {detail}")
            if sum(item["sample_count"] for item in worker_steps) != detail["total_sample_count"]:
                raise AssertionError("Weighted aggregation sample count evidence mismatch")
            if detail["timing"]["committed_at"] is None:
                raise AssertionError("Step has no durability-gated commit timestamp")

        all_started = self.events(attempt_id, "step.started")
        all_updated = self.events(attempt_id, "model.updated")
        all_applied = self.events(attempt_id, "parameter.applied")
        all_checkpoint_started = self.events(attempt_id, "checkpoint.started")
        all_checkpoint_saved = self.events(attempt_id, "checkpoint.saved")

        started = [item for item in all_started if item["details"]["operation_id"] < total_steps]
        updated = [item for item in all_updated if item["details"]["operation_id"] < total_steps]
        applied = [item for item in all_applied if item["details"]["operation_id"] < total_steps]
        checkpoint_started = [
            item
            for item in all_checkpoint_started
            if item["details"]["source_operation_id"] < total_steps
        ]
        checkpoint_saved = [
            item
            for item in all_checkpoint_saved
            if item["details"]["source_operation_id"] < total_steps
        ]

        if not (
            len(started)
            == len(updated)
            == len(checkpoint_started)
            == len(checkpoint_saved)
            == total_steps
            and len(applied) == total_steps * 3
        ):
            raise AssertionError("Per-step event cardinality invariant failed")
        by_operation_start = {item["details"]["operation_id"]: item for item in started}
        by_operation_update = {item["details"]["operation_id"]: item for item in updated}
        by_operation_checkpoint = {
            item["details"]["source_operation_id"]: item for item in checkpoint_saved
        }
        for operation in range(total_steps):
            start_event = by_operation_start[operation]
            update_event = by_operation_update[operation]
            saved_event = by_operation_checkpoint[operation]
            contributions = update_event["details"]["contributions"]
            if len(contributions) != 3 or {item["worker_id"] for item in contributions} != {
                0,
                1,
                2,
            }:
                raise AssertionError("Runtime update plan does not prove 3/3 contributions")
            if any(item["parameter_manifest_hash"] != parameter_hash for item in contributions):
                raise AssertionError("Contribution Parameter Manifest identity mismatch")
            ack_events = [item for item in applied if item["details"]["operation_id"] == operation]
            if len(ack_events) != 3 or {item["details"]["worker_id"] for item in ack_events} != {
                0,
                1,
                2,
            }:
                raise AssertionError("PARAMETER_APPLIED did not reach 3/3")
            if not (
                start_event["runtime_event_seq"]
                < update_event["runtime_event_seq"]
                < min(item["runtime_event_seq"] for item in ack_events)
                < saved_event["runtime_event_seq"]
            ):
                raise AssertionError("Update/apply/checkpoint causal order failed")
            next_start = by_operation_start.get(operation + 1)
            if next_start and saved_event["runtime_event_seq"] >= next_start["runtime_event_seq"]:
                raise AssertionError("Next Step opened before prior checkpoint commit")

        all_checkpoints = self.request(
            "GET", f"/api/v1/checkpoints?attempt_id={attempt_id}&limit=200"
        )["data"]
        if is_smoke:
            checkpoints = [
                item for item in all_checkpoints if item.get("source_operation_id", 0) < total_steps
            ]
            if len(checkpoints) < total_steps or any(
                item["state"] != "COMPLETE" for item in checkpoints
            ):
                raise AssertionError("Checkpoint projection count/state mismatch in smoke run")
        else:
            if len(all_checkpoints) != total_steps or any(
                item["state"] != "COMPLETE" for item in all_checkpoints
            ):
                raise AssertionError("Checkpoint projection count/state mismatch")
            checkpoints = all_checkpoints

        verified = 0
        for item in checkpoints:
            checkpoint_id = item["checkpoint_id"]
            directory = checkpoint_root / attempt_id / _sha256(checkpoint_id.encode())
            model_path = directory / "model.bin"
            metadata_path = directory / "checkpoint.json"
            model_bytes = model_path.read_bytes()
            metadata_bytes = metadata_path.read_bytes()
            metadata = json.loads(metadata_bytes)
            if (
                _canonical(metadata) != metadata_bytes
                or metadata["checkpoint_id"] != checkpoint_id
                or metadata["model"]["parameter_manifest_hash"] != parameter_hash
                or metadata["model"]["payload_sha256"] != _sha256(model_bytes)
                or metadata["model"]["payload_size_bytes"] != len(model_bytes)
            ):
                raise AssertionError(f"Checkpoint payload verification failed: {checkpoint_id}")
            verified += 1
        runtime = self.request("GET", "/api/v1/runtime/snapshot")["data"]
        attempt = self.request("GET", f"/api/v1/attempts/{attempt_id}")["data"]
        expected_state = "ABORTED" if is_smoke else "COMPLETED"
        if runtime["attempt_state"] != expected_state or runtime["model_version"] < total_steps:
            raise AssertionError(f"Runtime final state/version mismatch: {runtime}")
        if attempt["state"] != expected_state or attempt["model_version"] < total_steps:
            raise AssertionError(f"Backend/DB final state/version mismatch: {attempt}")
        self.result["workers"] = workers
        self.result["steps"] = total_steps
        self.result["initial_model_version"] = 0
        self.result["final_model_version"] = runtime["model_version"]
        self.result["final_runtime"] = runtime
        self.result["final_attempt"] = attempt
        self.result["checkpoints"] = {"count": len(checkpoints), "verified": verified}
        self.result["event_counts"] = {
            "step.started": len(started),
            "model.updated": len(updated),
            "parameter.applied": len(applied),
            "checkpoint.started": len(checkpoint_started),
            "checkpoint.saved": len(checkpoint_saved),
        }

    def finish(self, error: BaseException | None) -> None:
        if error is not None:
            self.result["verdict"] = "FAIL"
            self.result["failures"].append({"at": _now(), "error": repr(error)})
            self.result["duration_seconds"] = round(time.monotonic() - self.started_at, 3)
            self.result["finished_at"] = _now()
        for child in reversed(self.children):
            child.stop()
        (self.artifacts / "result.json").write_text(
            json.dumps(self.result, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        if error is None and not self.args.preserve_runtime_data:
            expected_parent = (self.repo / ".var" / "e2e").resolve()
            if self.runtime_data.parent != expected_parent:
                raise RuntimeError("Refusing to remove an unexpected runtime-data path")
            shutil.rmtree(self.runtime_data)
            self.log(f"removed disposable runtime data: {self.runtime_data}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run black-box E2E-HAPPY-01")
    parser.add_argument("--artifact-root", default="artifacts/e2e")
    parser.add_argument("--run-id")
    parser.add_argument("--reuse-runtime-data")
    parser.add_argument("--reuse-build-id")
    parser.add_argument("--reuse-dataset-id")
    parser.add_argument(
        "--database-url",
        default=None,
    )
    parser.add_argument("--postgres-bin")
    parser.add_argument("--postgres-port", type=int)
    parser.add_argument("--dataset-port", type=int)
    parser.add_argument("--backend-port", type=int)
    parser.add_argument("--management-port", type=int)
    parser.add_argument("--dtp-port", type=int)
    parser.add_argument("--batch-size", type=int, choices=(256, 512), default=256)
    parser.add_argument("--partition-seed", type=int, default=20260910)
    parser.add_argument("--training-seed", type=int, default=20260910)
    parser.add_argument("--learning-rate", type=float, default=0.01)
    parser.add_argument("--heartbeat-interval", type=float, default=5.0)
    parser.add_argument("--heartbeat-timeout", type=float, default=120.0)
    parser.add_argument("--poll-interval", type=float, default=5.0)
    parser.add_argument("--dataset-timeout", type=float, default=1800.0)
    parser.add_argument("--training-timeout", type=float, default=36000.0)
    parser.add_argument("--smoke-steps", type=int, default=0)
    parser.add_argument("--preserve-runtime-data", action="store_true")
    return parser


def main() -> None:
    harness = Harness(_parser().parse_args())
    error: BaseException | None = None
    try:
        result = harness.run()
        harness.log(
            f"PASS steps={result['steps']} final_model_version={result['final_model_version']} "
            f"duration_seconds={result['duration_seconds']}"
        )
    except BaseException as exc:
        error = exc
        harness.log(f"FAIL {type(exc).__name__}: {exc}")
    finally:
        harness.finish(error)
    if error is not None:
        raise error


if __name__ == "__main__":
    main()
