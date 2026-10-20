"""Real local cluster: Dataset Manager, PostgreSQL, Backend, Runtime and three Agents.

All orchestration uses public APIs and subprocesses; Workers are created only by
START_WORKER through their Agent supervisor. Evidence stays under artifacts/e2e.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import psutil

from e2e_local import Harness, _canonical, _now, _parser, _sha256
from local_fault_proxy import SlowPeerProxy


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
        self.reused_state = None
        if args.reuse_runtime_data:
            state_path = Path(args.reuse_runtime_data) / "smoke-state.json"
            self.reused_state = json.loads(state_path.read_text())
            for option, field in [
                ("reuse_build_id", "dataset_build_id"),
                ("reuse_dataset_id", "dataset_id"),
            ]:
                supplied = getattr(args, option)
                if supplied and supplied != self.reused_state[field]:
                    raise ValueError(f"{option} differs from persisted smoke state")
                setattr(args, option, self.reused_state[field])
            if args.dataset_port and args.dataset_port != self.reused_state["dataset_port"]:
                raise ValueError(
                    "Reused local artifact URLs require the original Dataset Manager port"
                )
            args.dataset_port = self.reused_state["dataset_port"]
            if args.storage_backend != self.reused_state["storage"]:
                raise ValueError("Storage backend differs from persisted smoke state")
        super().__init__(args)
        self.result["runtime_data"] = str(self.runtime_data)
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
        self.bind_host = "127.0.0.1"
        self.advertised_host = "127.0.0.1"
        self.agent_backend_url = self.base_url

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
                probe.bind((self.bind_host, port))
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
                self.args.model_id,
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
            "model_id": self.args.model_id,
            "numel": manifest["total_numel"],
            "parameter_manifest_hash": parameter_hash,
            "training_seed": self.args.training_seed,
        }
        self.result["dataset_manager_commit"] = subprocess.check_output(
            ["git", "-C", str(dm_repo), "rev-parse", "HEAD"], text=True
        ).strip()
        env[f"PARAMETER_MANIFEST_HASH_{self.args.model_id.upper()}"] = parameter_hash
        checkpoint_dir = self.artifacts / "checkpoints"
        self.start_child(
            "dataset-manager",
            [
                sys.executable,
                "-m",
                "dataset_manager.entrypoint",
                "--host",
                self.bind_host,
                "--port",
                str(self.dataset_port),
                "--store-dir",
                str(self.runtime_data / "datasets"),
                "--temp-dir",
                str(self.runtime_data / "datasets-tmp"),
                "--public-base-url",
                self.dataset_manager_url,
                "--storage-backend",
                self.args.storage_backend,
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
                self.bind_host,
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
        if self.args.scenario not in {"happy", "cache-reuse", "cache-repair", "workload-recovery"}:
            self.proxy = SlowPeerProxy(self.dtp_port)
        worker_port = self.proxy.port if self.proxy else self.dtp_port
        if getattr(self.args, "agents_before_backend", False):
            self.launch_agents(env)
        self.start_child(
            "backend",
            [
                sys.executable,
                "-m",
                "pbl4.management_backend.entrypoint",
                "--host",
                self.bind_host,
                "--port",
                str(self.backend_port),
                "--http",
                "h11",
            ],
            {
                **env,
                "RUNTIME_HOST": self.advertised_host,
                "RUNTIME_ADVERTISED_HOST": self.advertised_host,
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
        if not self.agent_dirs:
            self.launch_agents(env)
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
        if self.reused_state:
            ds = {"dataset_id": self.args.reuse_dataset_id}
            build = self.request("GET", f"/api/v1/dataset-builds/{self.args.reuse_build_id}")[
                "data"
            ]
        else:
            ds, build = self.create_dataset_build()
        build_id = build["dataset_build_id"]
        build = self.wait_value(
            lambda: self.request("GET", f"/api/v1/dataset-builds/{build_id}")["data"],
            lambda v: v["state"] in {"READY", "FAILED"},
            60,
            "Dataset Build READY",
        )
        if build["state"] != "READY":
            raise AssertionError(f"Build failed: {build}")
        summary = build["manifest_summary"]
        if (
            self.reused_state
            and summary["dataset_manifest_hash"] != self.reused_state["dataset_manifest_hash"]
        ):
            raise AssertionError("Reused Build manifest hash changed")
        import urllib.request

        with urllib.request.urlopen(summary["manifest_uri"], timeout=10) as res:
            raw = res.read()
        root = json.loads(raw)
        if _canonical(root) != raw or _sha256(raw) != summary["dataset_manifest_hash"]:
            raise AssertionError("Dataset manifest hash mismatch")
        if (
            root["dataset_id"] != "synthetic_smoke_v1"
            or root["sample_count"] != 192
            or root["shard_count"] != 3
        ):
            raise AssertionError("Unexpected smoke dataset provenance/size")
        total_units = sum(s["batch_count"] for s in root["shards"])
        total_steps = (total_units // self.args.work_units_per_step) * self.args.epochs
        if total_steps < 3:
            raise AssertionError("Smoke must complete at least 3 steps")
        self.result["dataset"] = {
            "dataset_id": ds["dataset_id"],
            "dataset_build_id": build_id,
            "dataset_manifest_hash": summary["dataset_manifest_hash"],
            "sample_count": root["sample_count"],
            "batch_size": 16,
            "source": "synthetic_smoke_v1",
            "storage": self.args.storage_backend,
            "build_reused": bool(self.reused_state),
        }
        self.result["workload"] = {
            "policy": self.args.workload_policy,
            "N": 3,
            "U": 16,
            "K": self.args.work_units_per_step,
            "epochs": self.args.epochs,
            "steps_per_epoch": total_units // self.args.work_units_per_step,
        }
        (self.runtime_data / "smoke-state.json").write_text(
            json.dumps(
                {
                    **self.result["dataset"],
                    "dataset_port": self.dataset_port,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        if self.args.scenario == "cache-repair":
            self.inject_cache_faults()
        job = self.request(
            "POST",
            "/api/v1/jobs",
            {
                "display_name": "Three Agent local smoke",
                "requested_contract": {
                    "dataset_build_id": build_id,
                    "model_id": self.args.model_id,
                    "epochs": self.args.epochs,
                    "learning_rate": 0.01,
                    "training_seed": self.args.training_seed,
                    "training_strategy": "strict_bsp",
                    "workload_policy": self.args.workload_policy,
                    "work_units_per_step": self.args.work_units_per_step,
                },
            },
            idempotency_key=self.run_id + "-job",
        )["data"]
        job_id = job["job_id"]
        validation = self.request("POST", f"/api/v1/jobs/{job_id}/validate")["data"]
        if validation["errors"]:
            raise AssertionError(f"Job validation failed: {validation}")
        started = self.request(
            "POST",
            f"/api/v1/jobs/{job_id}/start",
            {"node_ids": [n["node_id"] for n in nodes]},
            idempotency_key=self.run_id + "-start",
        )["data"]
        frozen = self.request("GET", f"/api/v1/jobs/{job_id}")["data"]
        resolved = frozen["resolved_contract"]["dataset"]
        if (
            resolved["dataset_build_id"] != build_id
            or resolved["dataset_manifest_hash"] != summary["dataset_manifest_hash"]
        ):
            raise AssertionError("Job did not freeze the selected Build identity")
        attempt_id = started["attempt_id"]
        self.result["job"] = {"job_id": job_id, "attempt_id": attempt_id, "execution_mode": "FRESH"}
        return self.run_attempt(
            env, nodes, job_id, attempt_id, total_steps, parameter_hash, checkpoint_dir
        )

    def launch_agents(self, env):
        for index in range(3):
            agent_dir = self.runtime_data / f"agent-{index}"
            self.agent_dirs.append(agent_dir)
            self.start_child(
                f"agent-{index}",
                [
                    sys.executable,
                    "-m",
                    "pbl4.node_agent.entrypoint",
                    "start",
                    "--backend-url",
                    self.agent_backend_url,
                    "--var-dir",
                    str(agent_dir),
                    "--heartbeat-interval",
                    "1",
                    "--telemetry-interval",
                    "1",
                ],
                env,
            )

    def create_dataset_build(self):
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
        return ds, build

    def run_attempt(
        self, env, nodes, job_id, attempt_id, total_steps, parameter_hash, checkpoint_dir
    ):
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
            if detail["total_sample_count"] != 16 * self.args.work_units_per_step or any(
                w["sample_count"] < 16
                or w["sample_count"] % 16
                or w["loss"] is None
                or w["compute_ms"] <= 0
                for w in values
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
        starts = self.events(attempt_id, "step.started")
        assignments = []
        for start in starts:
            detail = start["details"]
            worker_units = detail["assignments"]
            units = [u for a in worker_units for u in a["work_units"]]
            identities = {(u["shard_id"], u["batch_id"]) for u in units}
            if len(units) != self.args.work_units_per_step or len(identities) != len(units):
                raise AssertionError("Duplicate/incomplete canonical Work Unit assignment")
            if any(
                a["sample_count"] != sum(u["sample_count"] for u in a["work_units"])
                for a in worker_units
            ):
                raise AssertionError("Assignment sample count differs from Work Units")
            assignments.append(
                {
                    "epoch": detail["epoch"],
                    "operation_id": detail["operation_id"],
                    "workers": worker_units,
                }
            )
        self.result["assignments"] = assignments
        plans = self.events(attempt_id, "workload.plan_changed")
        self.result["workload_plans"] = plans
        if self.args.workload_policy == "dbs" and not all(
            any(p["details"]["epoch"] == epoch and p["details"]["policy"] == "dbs" for p in plans)
            for epoch in range(1, self.args.epochs)
        ):
            raise AssertionError("DBS plan was not applied at each epoch boundary")
        for plan in plans:
            counts = list(plan["details"]["units_per_worker"].values())
            if sum(counts) != self.args.work_units_per_step or min(counts) < 1:
                raise AssertionError("Workload plan violates fixed K or minimum per Worker")
        self.verify_cache_evidence(records)
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
        if self.args.scenario == "workload-recovery":
            self.check_workload_recovery(job_id, attempt_id, checkpoint_dir, total_steps)
        if getattr(self.args, "frontend_api_test", False):
            node = shutil.which("node")
            if not node:
                raise RuntimeError("Node.js unavailable for real frontend API acceptance")
            evidence = self.artifacts / "frontend-api-result.json"
            self.checked(
                "frontend-api",
                [
                    node,
                    str(self.repo / "web/node_modules/tsx/dist/cli.mjs"),
                    "--test",
                    str(self.repo / "web/src/api/__tests__/phase2LiveWorkflow.test.ts"),
                ],
                env={
                    **env,
                    "PBL4_API_SMOKE_URL": self.base_url,
                    "PBL4_API_SMOKE_BUILD_ID": self.result["dataset"]["dataset_build_id"],
                    "PBL4_API_SMOKE_EVIDENCE": str(evidence),
                },
            )
            self.result["frontend_api"] = json.loads(evidence.read_text())
        self.result["verdict"] = "PASS"
        if self.args.hold_seconds:
            self.log(
                f"holding services for UI inspection: {self.base_url} ({self.args.hold_seconds}s)"
            )
            time.sleep(self.args.hold_seconds)
        return self.result

    def verify_cache_evidence(self, records):
        pattern = re.compile(
            r"Dataset cache build_id=(\S+) manifest_hash=(\S+) shard_id=(\d+) "
            r"cache_reused=(True|False) bytes=(\d+)"
        )
        evidence = []
        for record in records:
            agent_dir = next(
                d
                for d in self.agent_dirs
                if record["allocation_id"] in json.loads((d / "allocations.json").read_text())
            )
            log = (agent_dir / f"worker-{record['allocation_id']}.log").read_text(errors="replace")
            matches = pattern.findall(log)
            if {int(m[2]) for m in matches} != {0, 1, 2} or len(matches) != 3:
                raise AssertionError("Worker did not report verification for all_shards")
            for build_id, manifest_hash, shard_id, reused, size in matches:
                if (
                    build_id != self.result["dataset"]["dataset_build_id"]
                    or manifest_hash != self.result["dataset"]["dataset_manifest_hash"]
                ):
                    raise AssertionError("Worker cache identity differs from frozen Build")
                evidence.append(
                    {
                        "allocation_id": record["allocation_id"],
                        "shard_id": int(shard_id),
                        "cache_reused": reused == "True",
                        "bytes_downloaded": int(size),
                    }
                )
        dm_log = (self.logs / "dataset-manager.log").read_text(errors="replace")
        paths = re.findall(r'"GET ([^ ]+) HTTP/1\.[01]" 200', dm_log)
        batch_requests = [p for p in paths if "/batches/" in p or p.endswith(".npz")]
        self.result["cache"] = {
            "shards": evidence,
            "worker_bytes_downloaded": sum(e["bytes_downloaded"] for e in evidence),
            "artifact_batch_http_requests": len(batch_requests),
            "artifact_http_paths": [p for p in paths if "/artifacts/" in p],
        }
        if (
            self.reused_state
            and self.args.scenario == "cache-reuse"
            and (
                any(not e["cache_reused"] or e["bytes_downloaded"] for e in evidence)
                or batch_requests
            )
        ):
            raise AssertionError("Warm run downloaded data instead of reusing all cached shards")
        if self.args.scenario == "cache-repair":
            misses = {
                (e["allocation_id"], e["shard_id"]) for e in evidence if not e["cache_reused"]
            }
            if len(misses) != 3 or len(batch_requests) != 2:
                raise AssertionError("Cache repair did not fetch exactly the two damaged batches")

    def inject_cache_faults(self):
        if not self.reused_state:
            raise ValueError("cache-repair requires --reuse-runtime-data")
        build = self.result["dataset"]
        faults = []
        for shard_id, agent_dir in enumerate(self.agent_dirs):
            key = _sha256(
                _canonical([build["dataset_build_id"], build["dataset_manifest_hash"], shard_id])
            )
            directory = agent_dir / "worker-cache" / key
            shard = json.loads((directory / "shard-manifest.json").read_text())
            batch = directory / shard["batches"][0]["relative_filename"]
            if shard_id == 0:
                batch.unlink()
                fault = "missing_batch"
            elif shard_id == 1:
                original = batch.read_bytes()
                batch.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                fault = "wrong_batch_hash"
            else:
                (directory / "dataset-manifest.json").write_bytes(b"{}")
                fault = "wrong_manifest_hash"
            faults.append({"agent": agent_dir.name, "shard_id": shard_id, "fault": fault})
        self.result["cache_faults"] = faults

    def data_fingerprints(self):
        roots = [self.runtime_data / "datasets", *(d / "worker-cache" for d in self.agent_dirs)]
        return {
            str(path.relative_to(self.runtime_data)): _sha256(path.read_bytes())
            for root in roots
            for path in root.rglob("*")
            if path.is_file()
            and (
                path.suffix == ".npz"
                or path.name in {"dataset-manifest.json", "shard-manifest.json"}
            )
        }

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
        if not saved or any(c["state"] != "COMPLETE" for c in saved):
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

    def check_workload_recovery(self, job_id, fresh_attempt, checkpoint_dir, total_steps):
        import numpy as np

        checkpoints = self.request(
            "GET", f"/api/v1/checkpoints?attempt_id={fresh_attempt}&limit=200"
        )["data"]
        checkpoints.sort(key=lambda c: c["model_version"])

        def payload(checkpoint, attempt):
            return (
                checkpoint_dir
                / attempt
                / _sha256(checkpoint["checkpoint_id"].encode())
                / "model.bin"
            )

        reference = payload(checkpoints[-1], fresh_attempt).read_bytes()
        cases = []
        for source in checkpoints[:2]:
            original = payload(source, fresh_attempt).read_bytes()
            resumed = self.request(
                "POST",
                f"/api/v1/jobs/{job_id}/resume",
                {"checkpoint_id": source["checkpoint_id"]},
                idempotency_key=self.run_id + f"-resume-{source['model_version']}",
            )["data"]
            attempt = resumed["attempt_id"]
            terminal = self.wait_value(
                lambda attempt=attempt: self._poll_attempt(attempt),
                lambda v: v["attempt"]["state"] in {"COMPLETED", "FAILED", "ABORTED"},
                120,
                "workload RESUME terminal",
            )
            if (
                terminal["attempt"]["state"] != "COMPLETED"
                or terminal["runtime"]["model_version"] != total_steps
            ):
                raise AssertionError("Workload RESUME failed or reset model version")
            remaining = total_steps - source["model_version"]
            steps = self.wait_value(
                lambda attempt=attempt: self.request(
                    "GET", f"/api/v1/attempts/{attempt}/steps?limit=200"
                )["data"],
                lambda values, remaining=remaining: (
                    len(values) == remaining and all(s["state"] == "COMMITTED" for s in values)
                ),
                20,
                "RESUME durable Steps",
            )
            if sorted(s["input_model_version"] for s in steps) != list(
                range(source["model_version"], total_steps)
            ):
                raise AssertionError("RESUME skipped or replayed RecoveryCursor")
            fresh_starts = self.events(fresh_attempt, "step.started")[source["model_version"] :]
            resumed_starts = self.events(attempt, "step.started")

            def identities(event):
                return sorted(
                    (u["shard_id"], u["batch_id"])
                    for a in event["details"]["assignments"]
                    for u in a["work_units"]
                )

            if [identities(e) for e in fresh_starts] != [identities(e) for e in resumed_starts]:
                raise AssertionError("RESUME global Work Units differ from uninterrupted run")
            saved = self.request("GET", f"/api/v1/checkpoints?attempt_id={attempt}&limit=200")[
                "data"
            ]
            if not saved or any(c["state"] != "COMPLETE" for c in saved):
                raise AssertionError("RESUME checkpoint count/state mismatch")
            for checkpoint in saved:
                data = payload(checkpoint, attempt).read_bytes()
                metadata = json.loads(
                    payload(checkpoint, attempt).with_name("checkpoint.json").read_bytes()
                )
                if metadata["model"]["payload_sha256"] != _sha256(data):
                    raise AssertionError("RESUME checkpoint hash mismatch")
            final = payload(max(saved, key=lambda c: c["model_version"]), attempt).read_bytes()
            np.testing.assert_allclose(
                np.frombuffer(final, dtype="<f4"),
                np.frombuffer(reference, dtype="<f4"),
                rtol=2e-5,
                atol=2e-6,
            )
            if payload(source, fresh_attempt).read_bytes() != original:
                raise AssertionError("RESUME modified source checkpoint")
            self.wait_value(
                lambda attempt=attempt: self.allocations(attempt),
                lambda values: (
                    len(values) == 3
                    and all(a["actual_state"] in {"ENDED", "FAILED"} for a in values)
                ),
                20,
                "RESUME allocation cleanup",
            )
            cases.append(
                {
                    "attempt_id": attempt,
                    "source_version": source["model_version"],
                    "steps": remaining,
                    "final_version": total_steps,
                    "matches_uninterrupted": True,
                    "workload_plans": self.events(attempt, "workload.plan_changed"),
                }
            )
        self.result["workload_resume"] = cases

    def finish(self, error):
        failures = []
        before_cleanup = self.data_fingerprints()
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
        after_cleanup = self.data_fingerprints()
        self.result["data_preserved_after_cleanup"] = before_cleanup == after_cleanup
        self.result["retained_artifact_files"] = len(after_cleanup)
        self.result["retained_artifact_tree_hash"] = _sha256(_canonical(after_cleanup))
        if before_cleanup != after_cleanup:
            failures.append("Process cleanup altered dataset/cache artifacts")
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
    from dotenv import load_dotenv

    load_dotenv()
    parser = _parser()
    parser.description = __doc__
    parser.add_argument("--dataset-manager-repo", required=True)
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument(
        "--scenario",
        choices=[
            "happy",
            "slow",
            "disconnect",
            "recovery",
            "agent-restart",
            "cache-reuse",
            "cache-repair",
            "workload-recovery",
        ],
        default="happy",
    )
    parser.add_argument(
        "--model-id", choices=["small_cnn", "resnet18_groupnorm"], default="small_cnn"
    )
    parser.add_argument("--workload-policy", choices=["equal", "dbs"], default="equal")
    parser.add_argument("--work-units-per-step", type=int, default=3)
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--agents-before-backend", action="store_true")
    parser.add_argument("--frontend-api-test", action="store_true")
    parser.add_argument(
        "--storage-backend",
        choices=["local", "huggingface"],
        default=os.environ.get("DATASET_STORAGE_BACKEND", "local"),
    )
    parser.set_defaults(
        batch_size=16, poll_interval=0.25, heartbeat_timeout=15, training_timeout=120
    )
    args = parser.parse_args()
    if not 0 <= args.hold_seconds <= 600:
        parser.error("--hold-seconds must be between 0 and 600")
    if args.database_url or args.dataset_manager_url:
        parser.error(
            "Agent smoke uses its private PostgreSQL cluster and subprocess Dataset Manager"
        )
    if args.scenario == "recovery" and args.model_id != "small_cnn":
        parser.error("Recovery numerical oracle uses SmallCNN; model-switch smoke uses cache-reuse")
    if not args.preserve_runtime_data:
        parser.error(
            "Agent smoke preserves reusable state; reset its local data explicitly after inspection"
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
