"""Real-process acceptance for managed DBS training and checkpoint resume.

The harness starts Runtime and Worker console entrypoints as independent OS
processes.  The parent process acts as the Management Backend MCP client and as
a fake immutable artifact origin.  No training implementation is called in
process by the harness.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from tests.fixtures.synthetic_dataset import (
    SyntheticDatasetArtifacts,
    create_synthetic_dataset_artifacts,
)

from pbl4.common.hashing import canonical_json_hash
from pbl4.common.worker_admission import issue_worker_join_token
from pbl4.management_backend.gateways.mcp_port import RealMcpClientPort
from pbl4.management_protocol.messages import AbortAttempt, StartAttempt


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_until(predicate, timeout: float, description: str):
    deadline = time.monotonic() + timeout
    last: object = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(0.05)
    raise TimeoutError(f"Timed out waiting for {description}; last={last!r}")


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        return None


@dataclass(slots=True)
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

    def assert_running(self) -> None:
        code = self.process.poll()
        if code is not None:
            output = self.log_path.read_text(encoding="utf-8", errors="replace")
            raise RuntimeError(f"{self.name} exited {code}:\n{output[-8000:]}")


@dataclass(frozen=True, slots=True)
class DatasetOrigin:
    artifacts: SyntheticDatasetArtifacts
    artifact_base_url: str
    manifest_uri: str
    root_manifest_path: str

    def resolution(self, request: dict[str, Any]) -> dict[str, object]:
        if (
            request["dataset_build_id"] != self.artifacts.dataset_build_id
            or request["expected_dataset_manifest_hash"] != self.artifacts.dataset_manifest_hash
        ):
            raise ValueError("Runtime requested an unpinned Dataset Build")
        return {
            "dataset_build_id": self.artifacts.dataset_build_id,
            "state": "READY",
            "manifest_uri": self.manifest_uri,
            "artifact_base_url": self.artifact_base_url,
            "dataset_manifest_hash": self.artifacts.dataset_manifest_hash,
            "profile": "CNN_IMAGE_CLASSIFICATION_V1",
            "shard_count": self.artifacts.root_manifest_dict["shard_count"],
            "batch_size": self.artifacts.root_manifest_dict["batch_size"],
        }


class Harness:
    def __init__(self, output: Path) -> None:
        self.repo = Path(__file__).resolve().parents[1]
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.logs = self.output / "logs"
        self.logs.mkdir()
        self.http_root = self.output / "artifact-origin"
        self.http_root.mkdir()
        handler = partial(_QuietHandler, directory=str(self.http_root))
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.http_thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.http_thread.start()
        self.http_url = f"http://127.0.0.1:{self.http.server_address[1]}"
        self.children: list[Child] = []
        self.clients: list[RealMcpClientPort] = []
        self.events: list[dict[str, Any]] = []
        self.parameter_manifest_path = self.output / "parameter-manifest.json"
        self._derive_parameter_manifest()
        manifest = json.loads(self.parameter_manifest_path.read_text(encoding="utf-8"))
        self.parameter_manifest_hash = str(manifest["parameter_manifest_hash"])
        self.admission_secret = "pbl4-e2e-managed-admission-secret"

    def _base_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.repo / "src") + os.pathsep + str(self.repo)
        env["PYTHONUNBUFFERED"] = "1"
        env["OMP_NUM_THREADS"] = "1"
        env["MKL_NUM_THREADS"] = "1"
        return env

    def _derive_parameter_manifest(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(self.repo / "scripts" / "derive_parameter_manifest.py"),
                "--output",
                str(self.parameter_manifest_path),
                "--seed",
                "20260925",
            ],
            cwd=self.repo,
            env=self._base_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError(completed.stdout.decode(errors="replace"))

    def start_child(
        self, name: str, command: list[str], *, env: dict[str, str] | None = None
    ) -> Child:
        log_path = self.logs / f"{name}.log"
        stream = log_path.open("wb")
        process = subprocess.Popen(
            command,
            cwd=self.repo,
            env=env or self._base_env(),
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        child = Child(name, process, stream, log_path)
        self.children.append(child)
        return child

    def create_origin(
        self,
        name: str,
        *,
        shard_count: int,
        batches_per_shard: int,
        root_manifest_path: str,
        hf_style: bool,
    ) -> DatasetOrigin:
        build_id = f"build-{name}"
        relative = (
            Path("hf") / "datasets" / "pbl4" / "resolve" / "main" / build_id
            if hf_style
            else Path("artifacts") / "v1" / "dataset-builds" / build_id
        )
        directory = self.http_root / relative
        artifacts = create_synthetic_dataset_artifacts(
            directory,
            dataset_build_id=build_id,
            shard_count=shard_count,
            batches_per_shard=batches_per_shard,
            batch_size=2,
            input_shape=(3, 8, 8),
        )
        if root_manifest_path != "dataset-manifest.json":
            (directory / root_manifest_path).write_bytes(artifacts.root_manifest_bytes)
        if not hf_style and root_manifest_path == "manifest.json":
            # Standalone Dataset Manager V1 exposes explicit legacy routes even
            # though immutable manifests retain their storage-relative names.
            for shard_id, shard_bytes in artifacts.shard_manifest_bytes.items():
                route_root = directory / "shards" / str(shard_id)
                (route_root / "batches").mkdir(parents=True, exist_ok=True)
                (route_root / "manifest.json").write_bytes(shard_bytes)
                for entry in artifacts.shard_manifest_dicts[shard_id]["batches"]:
                    (route_root / "batches" / str(entry["batch_id"])).write_bytes(
                        artifacts.batch_bytes[entry["relative_filename"]]
                    )
        base_url = f"{self.http_url}/{relative.as_posix()}"
        return DatasetOrigin(
            artifacts,
            base_url,
            f"{base_url}/{root_manifest_path}",
            root_manifest_path,
        )

    def start_runtime(self, name: str, checkpoint_root: Path) -> tuple[Child, int, int]:
        dtp_port = _free_port()
        management_port = _free_port()
        env = self._base_env()
        env["PBL4_WORKER_ADMISSION_SECRET"] = self.admission_secret
        child = self.start_child(
            name,
            [
                sys.executable,
                "-m",
                "pbl4.runtime.entrypoint",
                "--host",
                "127.0.0.1",
                "--port",
                str(dtp_port),
                "--management-port",
                str(management_port),
                "--dataset-manager-url",
                self.http_url,
                "--checkpoint-dir",
                str(checkpoint_root),
                "--parameter-manifest",
                str(self.parameter_manifest_path),
                "--heartbeat-timeout",
                "30",
            ],
            env=env,
        )
        return child, dtp_port, management_port

    def connect_backend(
        self, runtime: Child, management_port: int, origin: DatasetOrigin
    ) -> RealMcpClientPort:
        client = RealMcpClientPort("127.0.0.1", management_port, timeout=3.0)
        client.set_dataset_resolver(origin.resolution)

        def receive(kind: str, payload: dict[str, Any]) -> None:
            if kind == "RUNTIME_EVENT":
                self.events.append(payload)

        client.set_message_handler(receive)

        def try_connect() -> bool:
            runtime.assert_running()
            return client.connect()

        _wait_until(try_connect, 30, f"{runtime.name} MCP handshake")
        self.clients.append(client)
        return client

    def contract(
        self,
        origin: DatasetOrigin,
        *,
        expected_workers: int,
        epochs: int,
        workload_policy: str,
        work_units_per_step: int,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "dataset": {
                "dataset_build_id": origin.artifacts.dataset_build_id,
                "dataset_manifest_hash": origin.artifacts.dataset_manifest_hash,
                "profile": "CNN_IMAGE_CLASSIFICATION_V1",
                "batch_size": 2,
                "shard_count": expected_workers,
            },
            "model": {
                "model_id": "resnet18_groupnorm",
                "profile": "RESNET18_GROUPNORM_V1",
                "parameter_manifest_hash": self.parameter_manifest_hash,
            },
            "training": {"training_seed": 20260925, "epochs": epochs, "learning_rate": 0.01},
            "synchronization": {
                "training_strategy": "strict_bsp",
                "expected_workers": expected_workers,
            },
            "update_policy": {"type": "plain_sgd_without_momentum"},
            "checkpoint_policy": {
                "type": "after_each_model_update_blocking",
                "schema_version": 1,
            },
            "protocols": {"dtp_version": 1, "mcp_version": 1},
            "workload": {
                "policy": workload_policy,
                "work_units_per_step": work_units_per_step,
            },
        }

    def start_attempt(
        self,
        client: RealMcpClientPort,
        *,
        job_id: str,
        attempt_id: str,
        contract: dict[str, object],
        resume_checkpoint: dict[str, object] | None = None,
    ) -> str:
        contract_hash = canonical_json_hash(contract)
        execution_mode = "RESUME" if resume_checkpoint else "FRESH"
        checkpoint_id = (
            str(resume_checkpoint["checkpoint_id"]) if resume_checkpoint is not None else None
        )
        command_id = f"cmd-{uuid4().hex}"
        payload: dict[str, object] = {
            "command_id": command_id,
            "job_id": job_id,
            "attempt_id": attempt_id,
            "execution_mode": execution_mode,
            "resolved_contract": contract,
            "contract_hash": contract_hash,
            "resume_from_checkpoint_id": checkpoint_id,
            "requested_at": _now(),
        }
        if resume_checkpoint is not None:
            payload["resume_checkpoint"] = resume_checkpoint
        wire = StartAttempt.from_dict(payload).to_dict()
        if not client.send_command("START_ATTEMPT", command_id, attempt_id, wire):
            raise RuntimeError("Failed to dispatch START_ATTEMPT")
        return contract_hash

    def abort_attempt(self, client: RealMcpClientPort, *, job_id: str, attempt_id: str) -> None:
        command_id = f"cmd-{uuid4().hex}"
        payload = AbortAttempt.from_dict(
            {
                "command_id": command_id,
                "job_id": job_id,
                "attempt_id": attempt_id,
                "reason": "E2E restart boundary",
                "requested_at": _now(),
            }
        ).to_dict()
        if not client.send_command("ABORT_ATTEMPT", command_id, attempt_id, payload):
            raise RuntimeError("Failed to dispatch ABORT_ATTEMPT")

    def start_workers(
        self,
        prefix: str,
        *,
        dtp_port: int,
        attempt_id: str,
        count: int,
    ) -> list[Child]:
        children = []
        for index in range(count):
            allocation_id = f"allocation-{attempt_id}-{index}"
            node_id = f"node-{attempt_id}-{index}"
            token = issue_worker_join_token(
                self.admission_secret,
                attempt_id,
                allocation_id,
                node_id,
                ttl_seconds=1800,
            )
            env = self._base_env()
            env["PBL4_WORKER_JOIN_TOKEN"] = token
            children.append(
                self.start_child(
                    f"{prefix}-worker-{index}",
                    [
                        sys.executable,
                        "-m",
                        "pbl4.worker.entrypoint",
                        "--runtime-host",
                        "127.0.0.1",
                        "--runtime-port",
                        str(dtp_port),
                        "--node-label",
                        f"{prefix}-node-{index}",
                        "--cache-dir",
                        str(self.output / "cache" / prefix / str(index)),
                        "--initialization-seed",
                        "20260925",
                        "--heartbeat-interval",
                        "1",
                        "--attempt-id",
                        attempt_id,
                        "--allocation-id",
                        allocation_id,
                        "--node-id",
                        node_id,
                    ],
                    env=env,
                )
            )
        return children

    def wait_terminal(
        self,
        runtime: Child,
        client: RealMcpClientPort,
        expected: str,
        *,
        timeout: float = 600,
    ) -> dict[str, Any]:
        last: dict[str, Any] | None = None

        def poll() -> dict[str, Any] | None:
            nonlocal last
            runtime.assert_running()
            value = client.request_state()
            if value is not None:
                last = value
            return value if value is not None and value.get("attempt_state") == expected else None

        return _wait_until(poll, timeout, f"Runtime state {expected}")

    def wait_workers(self, workers: list[Child], expected_code: int) -> None:
        for worker in workers:
            try:
                code = worker.process.wait(timeout=60)
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(f"{worker.name} did not terminate") from exc
            if code != expected_code:
                output = worker.log_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(f"{worker.name} exited {code}:\n{output[-8000:]}")

    def events_for(self, attempt_id: str, event_type: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self.events
            if event.get("attempt_id") == attempt_id and event.get("event_type") == event_type
        ]

    def run_managed_dbs(self) -> dict[str, object]:
        origin = self.create_origin(
            "managed-dbs",
            shard_count=2,
            batches_per_shard=2,
            root_manifest_path="dataset-manifest.json",
            hf_style=True,
        )
        checkpoint_root = self.output / "managed-dbs-checkpoints"
        runtime, dtp_port, management_port = self.start_runtime(
            "managed-dbs-runtime", checkpoint_root
        )
        client = self.connect_backend(runtime, management_port, origin)
        attempt_id = "attempt-managed-dbs"
        contract = self.contract(
            origin,
            expected_workers=2,
            epochs=2,
            workload_policy="dbs",
            work_units_per_step=3,
        )
        self.start_attempt(
            client,
            job_id="job-managed-dbs",
            attempt_id=attempt_id,
            contract=contract,
        )
        workers = self.start_workers(
            "managed-dbs", dtp_port=dtp_port, attempt_id=attempt_id, count=2
        )
        final = self.wait_terminal(runtime, client, "COMPLETED")
        self.wait_workers(workers, 0)
        plans = self.events_for(attempt_id, "workload.plan_changed")
        if not any(
            event["details"].get("epoch") == 1 and event["details"].get("policy") == "dbs"
            for event in plans
        ):
            raise AssertionError(f"DBS epoch plan was not observed: {plans}")
        if final["model_version"] != 2:
            raise AssertionError(f"Unexpected managed DBS model version: {final}")
        return {
            "attempt_id": attempt_id,
            "state": final["attempt_state"],
            "model_version": final["model_version"],
            "root_manifest_path": origin.root_manifest_path,
            "artifact_base_url": origin.artifact_base_url,
            "plan_events": [event["details"] for event in plans],
        }

    def run_resume_after_restart(self) -> dict[str, object]:
        origin = self.create_origin(
            "resume",
            shard_count=1,
            batches_per_shard=4,
            root_manifest_path="manifest.json",
            hf_style=False,
        )
        checkpoint_root = self.output / "resume-checkpoints"
        job_id = "job-resume-restart"
        source_attempt = "attempt-resume-source"
        contract = self.contract(
            origin,
            expected_workers=1,
            epochs=3,
            workload_policy="dbs",
            work_units_per_step=2,
        )

        runtime1, dtp1, mcp1 = self.start_runtime("resume-source-runtime", checkpoint_root)
        client1 = self.connect_backend(runtime1, mcp1, origin)
        self.start_attempt(
            client1,
            job_id=job_id,
            attempt_id=source_attempt,
            contract=contract,
        )
        source_workers = self.start_workers(
            "resume-source", dtp_port=dtp1, attempt_id=source_attempt, count=1
        )

        def first_checkpoint() -> dict[str, Any] | None:
            runtime1.assert_running()
            saved = self.events_for(source_attempt, "checkpoint.saved")
            return saved[0] if saved else None

        checkpoint_event = _wait_until(first_checkpoint, 600, "first durable checkpoint")
        self.abort_attempt(client1, job_id=job_id, attempt_id=source_attempt)
        self.wait_terminal(runtime1, client1, "ABORTED")
        self.wait_workers(source_workers, 1)
        details = checkpoint_event["details"]
        descriptor = {
            "checkpoint_id": details["checkpoint_id"],
            "source_attempt_id": source_attempt,
            "model_sha256": details["model_sha256"],
            "metadata_sha256": details["metadata_sha256"],
        }
        source_model_version = int(details["model_version"])
        client1.disconnect()
        runtime1.stop()

        resumed_attempt = "attempt-resume-restored"
        runtime2, dtp2, mcp2 = self.start_runtime("resume-restored-runtime", checkpoint_root)
        client2 = self.connect_backend(runtime2, mcp2, origin)
        self.start_attempt(
            client2,
            job_id=job_id,
            attempt_id=resumed_attempt,
            contract=contract,
            resume_checkpoint=descriptor,
        )
        resumed_workers = self.start_workers(
            "resume-restored", dtp_port=dtp2, attempt_id=resumed_attempt, count=1
        )
        final = self.wait_terminal(runtime2, client2, "COMPLETED")
        self.wait_workers(resumed_workers, 0)
        updates = self.events_for(resumed_attempt, "model.updated")
        if (
            not updates
            or int(updates[0]["details"]["output_model_version"]) != source_model_version + 1
        ):
            raise AssertionError("Resumed Runtime did not continue from restored model_version")
        plans = self.events_for(resumed_attempt, "workload.plan_changed")
        policies = {
            int(event["details"]["epoch"]): str(event["details"]["policy"]) for event in plans
        }
        if policies.get(1) != "equal" or policies.get(2) != "dbs":
            raise AssertionError(f"Mid-epoch resume warm-up semantics failed: {plans}")
        return {
            "source_attempt_id": source_attempt,
            "resumed_attempt_id": resumed_attempt,
            "checkpoint_id": descriptor["checkpoint_id"],
            "restored_model_version": source_model_version,
            "final_model_version": final["model_version"],
            "final_state": final["attempt_state"],
            "root_manifest_path": origin.root_manifest_path,
            "plan_events": [event["details"] for event in plans],
        }

    def finish(self) -> None:
        for client in self.clients:
            client.disconnect()
        for child in reversed(self.children):
            child.stop()
        self.http.shutdown()
        self.http.server_close()
        self.http_thread.join(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise ValueError("E2E output directory must not already exist")
    harness = Harness(output)
    result: dict[str, object] = {"started_at": _now()}
    error: BaseException | None = None
    try:
        result["managed_dbs"] = harness.run_managed_dbs()
        result["resume_after_restart"] = harness.run_resume_after_restart()
        result["verdict"] = "PASS"
    except BaseException as exc:
        error = exc
        result["verdict"] = "FAIL"
        result["error"] = repr(exc)
    finally:
        result["finished_at"] = _now()
        (output / "result.json").write_text(
            json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
        harness.finish()
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    if error is not None:
        raise error


if __name__ == "__main__":
    main()
