"""Real local cluster: Dataset Manager, PostgreSQL, Backend, Runtime and three Agents.

All orchestration uses public APIs and subprocesses; Workers are created only by
START_WORKER through their Agent supervisor. Evidence stays under artifacts/e2e.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

from e2e_local import Harness, _canonical, _now, _parser, _sha256
from local_fault_proxy import SlowPeerProxy


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if key in {"enrollment_code", "node_secret", "worker_join_token", "code_hash"}
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def stop_tree(proc):
    """Stop only this harness-owned tree, including Windows venv launchers."""
    children = proc.children(recursive=True)
    for item in [*reversed(children), proc]:
        with contextlib.suppress(psutil.NoSuchProcess):
            item.terminate()
    _, alive = psutil.wait_procs([*children, proc], timeout=10)
    for item in alive:
        item.kill()
    _, alive = psutil.wait_procs(alive, timeout=5)
    if alive:
        raise RuntimeError(f"Processes survived cleanup: {[p.pid for p in alive]}")


class AgentHarness(Harness):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.result["case"] = "LOCAL-THREE-AGENTS"
        self.result["source_commit"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, text=True
        ).strip()
        self.result["working_tree_dirty"] = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=self.repo, text=True
            ).strip()
        )
        self.agent_dirs: list[Path] = []
        self.proxy = None

    def request(self, method, path, body=None, **kwargs):
        # The enrollment response contains a one-time credential. Keep it out of
        # evidence without modifying the response consumed by the enrollment CLI.
        if path == "/api/v1/nodes/enrollment-codes":
            import urllib.request

            req = urllib.request.Request(
                self.base_url + path,
                data=_canonical(body or {}),
                headers={"Content-Type": "application/json"},
                method=method,
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                value = json.load(response)
            with self.evidence_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"at": _now(), "path": path, "body": redact(value)}) + "\n")
            return value
        return super().request(method, path, body, **kwargs)

    def checked(self, name, command, *, env=None):
        with (self.logs / f"{name}.log").open("wb") as stream:
            process = subprocess.Popen(
                command,
                cwd=self.repo,
                env=env,
                stdout=stream,
                stderr=subprocess.STDOUT,
            )
            try:
                code = process.wait(timeout=90)
            except BaseException:
                with contextlib.suppress(psutil.NoSuchProcess):
                    stop_tree(psutil.Process(process.pid))
                raise
        if code:
            raise RuntimeError(f"{name} exited {code}; see {self.logs / name}.log")
        self.log(f"completed {name}")

    def allocations(self, attempt_id):
        import psycopg
        from psycopg.rows import dict_row

        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            return conn.execute(
                "SELECT allocation_id, node_id, actual_state, desired_state "
                "FROM worker_allocations WHERE attempt_id = %s",
                (attempt_id,),
            ).fetchall()

    def run(self):
        dm_repo = Path(self.args.dataset_manager_repo).resolve()
        if not (dm_repo / "src/dataset_manager/entrypoint.py").is_file():
            raise RuntimeError("--dataset-manager-repo must name the real Dataset Manager checkout")
        ports = [
            self.backend_port,
            self.dataset_port,
            self.management_port,
            self.dtp_port,
            self.postgres_port,
        ]
        if len(set(ports)) != len(ports):
            raise ValueError("Service ports must be distinct")
        for port in ports:
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", port))
        env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "PYTHONPATH": str(self.repo / "src"),
            "OMP_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "PBL4_WORKER_ADMISSION_SECRET": secrets.token_urlsafe(32),
        }
        self.setup_postgres(env)
        env["DATABASE_URL"] = self.database_url
        self.checked("migrate", [sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        manifest_path = self.artifacts / "parameter-manifest.json"
        self.checked(
            "manifest",
            [
                sys.executable,
                "scripts/derive_parameter_manifest.py",
                "--model-id",
                "small_cnn",
                "--seed",
                str(self.args.training_seed),
                "--output",
                str(manifest_path),
            ],
            env=env,
        )
        manifest = json.loads(manifest_path.read_text())
        parameter_hash = manifest["parameter_manifest_hash"]
        self.result["model"] = {
            "model_id": "small_cnn",
            "numel": manifest["total_numel"],
            "parameter_manifest_hash": parameter_hash,
            "training_seed": self.args.training_seed,
        }
        self.result["dataset_manager_commit"] = subprocess.check_output(
            ["git", "-C", str(dm_repo), "rev-parse", "HEAD"], text=True
        ).strip()
        env["PARAMETER_MANIFEST_HASH_SMALL_CNN"] = parameter_hash
        checkpoint_dir = self.artifacts / "checkpoints"
        self.start_child(
            "dataset-manager",
            [
                sys.executable,
                "-m",
                "dataset_manager.entrypoint",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.dataset_port),
                "--store-dir",
                str(self.runtime_data / "datasets"),
                "--temp-dir",
                str(self.runtime_data / "datasets-tmp"),
                "--public-base-url",
                self.dataset_manager_url,
                "--storage-backend",
                "local",
                "--http",
                "h11",
            ],
            {**env, "PYTHONPATH": str(dm_repo / "src")},
        )
        self.wait_http(self.dataset_manager_url + "/healthz", 30, "Dataset Manager")
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
                self.dataset_manager_url,
                "--checkpoint-dir",
                str(checkpoint_dir),
                "--parameter-manifest",
                str(manifest_path),
                "--heartbeat-timeout",
                str(self.args.heartbeat_timeout),
            ],
            env,
        )
        if self.args.scenario != "happy":
            self.proxy = SlowPeerProxy(self.dtp_port)
        worker_port = self.proxy.port if self.proxy else self.dtp_port
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
                "--http",
                "h11",
            ],
            {
                **env,
                "RUNTIME_HOST": "127.0.0.1",
                "RUNTIME_ADVERTISED_HOST": "127.0.0.1",
                "RUNTIME_PORT": str(worker_port),
                "RUNTIME_MANAGEMENT_PORT": str(self.management_port),
                "DATASET_MANAGER_URL": self.dataset_manager_url,
                "EXPECTED_WORKERS": "3",
                "NODE_HEARTBEAT_INTERVAL_SECONDS": "1",
                "NODE_TELEMETRY_INTERVAL_SECONDS": "1",
            },
        )
        self.wait_http(self.base_url + "/api/v1/health", 60, "Backend")
        self.wait_value(
            lambda: self.request("GET", "/api/v1/runtime/snapshot")["data"],
            lambda v: not v["stale"] and bool(v["runtime_instance_id"]),
            60,
            "MCP ready",
        )
        for index in range(3):
            agent_dir = self.runtime_data / f"agent-{index}"
            self.agent_dirs.append(agent_dir)
            code = self.request("POST", "/api/v1/nodes/enrollment-codes")["data"]["enrollment_code"]
            self.checked(
                f"enroll-{index}",
                [
                    sys.executable,
                    "-m",
                    "pbl4.node_agent.entrypoint",
                    "enroll",
                    "--backend-url",
                    self.base_url,
                    "--var-dir",
                    str(agent_dir),
                ],
                env={**env, "PBL4_ENROLLMENT_CODE": code},
            )
            self.start_child(
                f"agent-{index}",
                [
                    sys.executable,
                    "-m",
                    "pbl4.node_agent.entrypoint",
                    "start",
                    "--backend-url",
                    self.base_url,
                    "--var-dir",
                    str(agent_dir),
                    "--heartbeat-interval",
                    "1",
                    "--telemetry-interval",
                    "1",
                ],
                env,
            )
        nodes = self.wait_value(
            lambda: self.request("GET", "/api/v1/nodes")["data"],
            lambda v: len(v) == 3 and all(n["state"] == "ONLINE" for n in v),
            45,
            "3 Agents ONLINE",
        )
        self.result["nodes"] = nodes
        self.result["agent_pids"] = [
            c.process.pid for c in self.children if c.name.startswith("agent-")
        ]
        ds = self.request(
            "POST",
            "/api/v1/datasets",
            {
                "name": "Synthetic local smoke (not CIFAR-10)",
                "task_type": "image_classification",
                "source_type": "builtin",
                "source_reference": "synthetic_smoke_v1",
            },
            idempotency_key=self.run_id + "-dataset",
        )["data"]
        build = self.request(
            "POST",
            "/api/v1/dataset-builds",
            {
                "dataset_id": ds["dataset_id"],
                "profile": "CNN_IMAGE_CLASSIFICATION_V1",
                "batch_size": 16,
                "partition_seed": self.args.partition_seed,
            },
            idempotency_key=self.run_id + "-build",
        )["data"]
        build_id = build["dataset_build_id"]
        build = self.wait_value(
            lambda: self.request("GET", f"/api/v1/dataset-builds/{build_id}")["data"],
            lambda v: v["state"] in {"READY", "FAILED"},
            60,
            "Dataset Build READY",
        )
        if build["state"] != "READY":
            raise AssertionError(f"Build failed: {build}")
        import urllib.request

        with urllib.request.urlopen(
            build["manifest_summary"]["artifact_base_url"] + "/manifest.json", timeout=10
        ) as res:
            raw = res.read()
        root = json.loads(raw)
        if (
            _canonical(root) != raw
            or _sha256(raw) != build["manifest_summary"]["dataset_manifest_hash"]
        ):
            raise AssertionError("Dataset manifest hash mismatch")
        if (
            root["dataset_id"] != "synthetic_smoke_v1"
            or root["sample_count"] != 192
            or root["shard_count"] != 3
        ):
            raise AssertionError("Unexpected smoke dataset provenance/size")
        total_steps = root["batch_count_per_shard"]
        if total_steps < 3:
            raise AssertionError("Smoke must complete at least 3 steps")
        self.result["dataset"] = {
            "dataset_id": ds["dataset_id"],
            "dataset_build_id": build_id,
            "sample_count": root["sample_count"],
            "batch_size": 16,
            "source": "synthetic_smoke_v1",
            "storage": "local",
        }
        job = self.request(
            "POST",
            "/api/v1/jobs",
            {
                "display_name": "Three Agent local smoke",
                "requested_contract": {
                    "dataset_build_id": build_id,
                    "model_id": "small_cnn",
                    "epochs": 1,
                    "learning_rate": 0.01,
                    "training_seed": self.args.training_seed,
                    "training_strategy": "strict_bsp",
                },
            },
            idempotency_key=self.run_id + "-job",
        )["data"]
        job_id = job["job_id"]
        validation = self.request("POST", f"/api/v1/jobs/{job_id}/validate")["data"]
        if validation["errors"]:
            raise AssertionError(f"Job validation failed: {validation}")
        started = self.request(
            "POST", f"/api/v1/jobs/{job_id}/start", {}, idempotency_key=self.run_id + "-start"
        )["data"]
        attempt_id = started["attempt_id"]
        self.result["job"] = {"job_id": job_id, "attempt_id": attempt_id, "execution_mode": "FRESH"}
        if self.args.scenario == "agent-restart":
            self.wait_value(
                lambda: self._poll_smoke(attempt_id),
                lambda v: len(v["steps"]) >= 1,
                60,
                "first durable Step before Agent restart",
            )
            agent = next(c for c in self.children if c.name == "agent-0")
            record = next(
                iter(json.loads((self.agent_dirs[0] / "allocations.json").read_text()).values())
            )
            worker = psutil.Process(record["pid"])
            root_process = psutil.Process(agent.process.pid)
            # Stop only Agent interpreters, leaving the supervised Worker tree intact.
            interpreters = [
                p
                for p in root_process.children(recursive=True)
                if "pbl4.node_agent.entrypoint" in p.cmdline()
            ]
            for proc in [*interpreters, root_process]:
                proc.terminate()
            psutil.wait_procs([*interpreters, root_process], timeout=5)
            agent.process.wait(5)
            agent.stream.close()
            self.children.remove(agent)
            if not worker.is_running() or abs(worker.create_time() - record["create_time"]) >= 0.01:
                raise AssertionError("Agent loss terminated the Worker")
            replacement = self.start_child("agent-0-restarted", agent.process.args, env)
            self.wait_value(
                lambda: replacement.log_path.read_text(errors="replace"),
                lambda v: "1 active worker processes surviving" in v and "Received HELLO_ACK" in v,
                30,
                "Agent reconciled surviving Worker",
            )
            self.result["agent_restart"] = {
                "old_agent_pid": agent.process.pid,
                "new_agent_pid": replacement.process.pid,
                "surviving_worker_pid": worker.pid,
                "allocation_id": record["allocation_id"],
            }
        if self.args.scenario == "disconnect":
            self.wait_value(
                lambda: self._poll_smoke(attempt_id),
                lambda v: len(v["steps"]) >= 1,
                60,
                "first durable Step",
            )
            workers = self.request("GET", f"/api/v1/attempts/{attempt_id}/workers")["data"]
            allocation = next(w["allocation_id"] for w in workers if w["worker_id"] == 0)
            record = next(
                r
                for d in self.agent_dirs
                for r in json.loads((d / "allocations.json").read_text()).values()
                if r["allocation_id"] == allocation
            )
            proc = psutil.Process(record["pid"])
            if abs(proc.create_time() - record["create_time"]) >= 0.01:
                raise AssertionError("Worker PID changed before fault injection")
            stop_tree(proc)
            failed = self.wait_value(
                lambda: self._poll_attempt(attempt_id),
                lambda v: v["attempt"]["state"] in {"FAILED", "COMPLETED", "ABORTED"},
                45,
                "Worker loss detected",
            )
            if (
                failed["attempt"]["state"] != "FAILED"
                or failed["runtime"]["model_version"] >= total_steps
            ):
                raise AssertionError("Disconnect did not fail fixed-membership Attempt")
            updates = self.events(attempt_id, "model.updated")
            if any(len(e["details"]["contributions"]) != 3 for e in updates):
                raise AssertionError("Partial update after Worker loss")
            self.result["disconnect"] = {
                "attempt_id": attempt_id,
                "state": "FAILED",
                "model_version": failed["runtime"]["model_version"],
                "full_membership_updates": len(updates),
            }
            self.wait_value(
                lambda: self.allocations(attempt_id),
                lambda v: len(v) == 3 and all(n["actual_state"] in {"ENDED", "FAILED"} for n in v),
                30,
                "allocation cleanup",
            )
            retry = self.request(
                "POST", f"/api/v1/jobs/{job_id}/retry", {}, idempotency_key=self.run_id + "-retry"
            )["data"]
            attempt_id = retry["attempt_id"]
            self.result["job"]["retry_attempt_id"] = attempt_id
        terminal = self.wait_value(
            lambda: self._poll_attempt(attempt_id),
            lambda v: v["attempt"]["state"] in {"COMPLETED", "FAILED", "ABORTED"},
            self.args.training_timeout,
            "Attempt terminal",
        )
        if terminal["attempt"]["state"] != "COMPLETED":
            raise AssertionError(f"Attempt failed: {terminal}")
        self.wait_value(
            lambda: self.request("GET", f"/api/v1/attempts/{attempt_id}/steps?limit=200")["data"],
            lambda v: len(v) == total_steps and all(s["state"] == "COMMITTED" for s in v),
            20,
            "durable Step projections",
        )
        self.verify(attempt_id, total_steps, parameter_hash, checkpoint_dir)
        self.result["step_metrics"] = []
        for step in self.request("GET", f"/api/v1/attempts/{attempt_id}/steps?limit=200")["data"]:
            detail = self.request("GET", f"/api/v1/attempts/{attempt_id}/steps/{step['step_id']}")[
                "data"
            ]
            values = detail["worker_steps"]
            if detail["total_sample_count"] != 48 or any(
                w["sample_count"] != 16 or w["loss"] is None or w["compute_ms"] <= 0 for w in values
            ):
                raise AssertionError("Missing real loss/compute/sample count evidence")
            self.result["step_metrics"].append(
                {
                    "step_id": step["step_id"],
                    "loss": detail["metrics"]["loss"],
                    "total_sample_count": detail["total_sample_count"],
                    "workers": [
                        {k: w[k] for k in ["worker_id", "loss", "compute_ms", "sample_count"]}
                        for w in values
                    ],
                }
            )
        records = []
        for agent_dir in self.agent_dirs:
            local = json.loads((agent_dir / "allocations.json").read_text())
            current = [r for r in local.values() if r["attempt_id"] == attempt_id]
            if len(current) != 1:
                raise AssertionError("Each Agent must supervise exactly one Worker")
            records.extend(current)
        if len({r["pid"] for r in records}) != 3:
            raise AssertionError("Worker processes must be distinct")
        if {w["allocation_id"] for w in self.result["workers"]} != {
            r["allocation_id"] for r in records
        }:
            raise AssertionError("Runtime membership does not match Agent-spawned processes")
        if {w["node_id"] for w in self.result["workers"]} != {n["node_id"] for n in nodes}:
            raise AssertionError("Runtime membership does not match enrolled Nodes")
        self.result["worker_processes"] = records
        self.result["allocations"] = self.wait_value(
            lambda: self.allocations(attempt_id),
            lambda v: len(v) == 3 and all(n["actual_state"] in {"ENDED", "FAILED"} for n in v),
            20,
            "terminal Allocations",
        )
        if self.proxy:
            self.result["network_fault"] = {
                "connections": self.proxy.connections,
                "delayed_reads": self.proxy.delays,
                "delay_ms": [100, 200, 300],
            }
        self.result["scenario"] = self.args.scenario
        if self.args.scenario == "recovery":
            self.check_recovery(job_id, attempt_id, checkpoint_dir, parameter_hash)
        self.result["verdict"] = "PASS"
        if self.args.hold_seconds:
            self.log(
                f"holding services for UI inspection: {self.base_url} ({self.args.hold_seconds}s)"
            )
            time.sleep(self.args.hold_seconds)
        return self.result

    def check_recovery(self, job_id, fresh_attempt, checkpoint_dir, parameter_hash):
        import numpy as np

        checkpoints = self.request(
            "GET", f"/api/v1/checkpoints?attempt_id={fresh_attempt}&limit=200"
        )["data"]
        checkpoints.sort(key=lambda c: c["model_version"])
        source = checkpoints[0]

        def payload(checkpoint, attempt):
            return (
                checkpoint_dir
                / attempt
                / _sha256(checkpoint["checkpoint_id"].encode())
                / "model.bin"
            )

        reference = payload(checkpoints[-1], fresh_attempt).read_bytes()
        resumed = self.request(
            "POST",
            f"/api/v1/jobs/{job_id}/resume",
            {"checkpoint_id": source["checkpoint_id"]},
            idempotency_key=self.run_id + "-resume",
        )["data"]
        attempt_id = resumed["attempt_id"]
        terminal = self.wait_value(
            lambda: self._poll_attempt(attempt_id),
            lambda v: v["attempt"]["state"] in {"COMPLETED", "FAILED", "ABORTED"},
            90,
            "RESUME terminal",
        )
        if terminal["attempt"]["state"] != "COMPLETED" or terminal["runtime"]["model_version"] != 4:
            raise AssertionError("RESUME did not restore version/cursor and finish")
        steps = self.wait_value(
            lambda: self.request("GET", f"/api/v1/attempts/{attempt_id}/steps?limit=200")["data"],
            lambda v: len(v) == 3 and all(s["state"] == "COMMITTED" for s in v),
            20,
            "RESUME committed Steps",
        )
        if sorted(s["input_model_version"] for s in steps) != [1, 2, 3]:
            raise AssertionError("RESUME reset the model version")
        for step in steps:
            detail = self.request("GET", f"/api/v1/attempts/{attempt_id}/steps/{step['step_id']}")[
                "data"
            ]
            if len(detail["worker_steps"]) != 3 or detail["total_sample_count"] != 48:
                raise AssertionError("RESUME lost full membership or sample weighting")
        saved = self.request("GET", f"/api/v1/checkpoints?attempt_id={attempt_id}&limit=200")[
            "data"
        ]
        if len(saved) != 3 or any(c["state"] != "COMPLETE" for c in saved):
            raise AssertionError("RESUME checkpoints incomplete")
        for checkpoint in saved:
            model_bytes = payload(checkpoint, attempt_id).read_bytes()
            metadata_bytes = (
                payload(checkpoint, attempt_id).with_name("checkpoint.json").read_bytes()
            )
            metadata = json.loads(metadata_bytes)
            if (
                metadata["model"]["payload_sha256"] != _sha256(model_bytes)
                or metadata["model"]["parameter_manifest_hash"] != parameter_hash
            ):
                raise AssertionError("RESUME checkpoint integrity mismatch")
        final = payload(max(saved, key=lambda c: c["model_version"]), attempt_id).read_bytes()
        # Reuse the established SmallCNN network oracle tolerance.
        np.testing.assert_allclose(
            np.frombuffer(final, dtype="<f4"),
            np.frombuffer(reference, dtype="<f4"),
            rtol=2e-5,
            atol=2e-6,
        )
        self.wait_value(
            lambda: self.allocations(attempt_id),
            lambda v: len(v) == 3 and all(a["actual_state"] in {"ENDED", "FAILED"} for a in v),
            20,
            "RESUME Allocation cleanup",
        )
        self.result["resume"] = {
            "attempt_id": attempt_id,
            "steps": 3,
            "initial_version": 1,
            "final_version": 4,
            "checkpoints_verified": 3,
            "matches_uninterrupted": True,
        }
        source_path = payload(source, fresh_attempt)
        original = source_path.read_bytes()
        for fault in ["corrupt", "missing"]:
            try:
                if fault == "corrupt":
                    source_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                else:
                    source_path.unlink()
                rejected = self.request(
                    "POST",
                    f"/api/v1/jobs/{job_id}/resume",
                    {"checkpoint_id": source["checkpoint_id"]},
                    idempotency_key=self.run_id + "-" + fault,
                )["data"]
                bad_id = rejected["attempt_id"]
                failed = self.wait_value(
                    lambda bad_id=bad_id: self._poll_attempt(bad_id),
                    lambda v: v["attempt"]["state"] in {"FAILED", "COMPLETED", "ABORTED"},
                    60,
                    fault + " checkpoint rejected",
                )
                if (
                    failed["attempt"]["state"] != "FAILED"
                    or failed["runtime"]["model_version"] != 0
                ):
                    raise AssertionError(f"Training continued with {fault} checkpoint")
                self.wait_value(
                    lambda bad_id=bad_id: self.allocations(bad_id),
                    lambda v: all(a["actual_state"] in {"ENDED", "FAILED"} for a in v),
                    20,
                    fault + " Allocation cleanup",
                )
                self.result[fault + "_checkpoint"] = {
                    "attempt_id": bad_id,
                    "state": "FAILED",
                    "model_version": 0,
                }
            finally:
                source_path.write_bytes(original)

    def finish(self, error):
        failures = []
        if self.proxy:
            try:
                self.proxy.close()
            except Exception as exc:
                failures.append(str(exc))
        # Agents intentionally leave Workers alive on control disconnect. The
        # harness owns cleanup; verify persisted PID/create-time before stopping.
        for agent_dir in self.agent_dirs:
            path = agent_dir / "allocations.json"
            if path.is_file():
                for record in json.loads(path.read_text()).values():
                    try:
                        proc = psutil.Process(record["pid"])
                        if abs(proc.create_time() - record["create_time"]) < 0.01:
                            stop_tree(proc)
                    except psutil.NoSuchProcess:
                        pass
                    except Exception as exc:
                        failures.append(str(exc))
        for child in reversed(self.children):
            try:
                if child.process.poll() is None:
                    stop_tree(psutil.Process(child.process.pid))
                child.stop()
            except Exception as exc:
                failures.append(f"{child.name}: {exc}")
        self.result["cleanup"] = failures if failures else "PASS"
        self.result["finished_at"] = _now()
        self.result["duration_seconds"] = round(time.monotonic() - self.started_at, 3)
        if error or failures:
            self.result["verdict"] = "FAIL"
            self.result["failures"].append(repr(error) if error else failures)
        (self.artifacts / "result.json").write_text(
            json.dumps(self.result, indent=2, default=str), encoding="utf-8"
        )
        if failures:
            raise RuntimeError(f"Cleanup failed: {failures}")


def main():
    parser = _parser()
    parser.description = __doc__
    parser.add_argument("--dataset-manager-repo", required=True)
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument(
        "--scenario",
        choices=["happy", "slow", "disconnect", "recovery", "agent-restart"],
        default="happy",
    )
    parser.set_defaults(
        batch_size=16, poll_interval=0.25, heartbeat_timeout=15, training_timeout=120
    )
    args = parser.parse_args()
    if not 0 <= args.hold_seconds <= 600:
        parser.error("--hold-seconds must be between 0 and 600")
    if args.database_url or args.reuse_runtime_data or args.dataset_manager_url:
        parser.error(
            "Agent smoke uses a fresh private PostgreSQL cluster and local Dataset Manager"
        )
    harness = AgentHarness(args)
    error = None
    try:
        harness.run()
    except BaseException as exc:
        error = exc
        harness.log(f"FAIL {type(exc).__name__}: {exc}")
    finally:
        harness.finish(error)
    if error:
        raise error
    harness.log(f"PASS steps={harness.result['steps']} cleanup=PASS artifacts={harness.artifacts}")


if __name__ == "__main__":
    main()
