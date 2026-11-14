"""Archive a training run; optional psutil supplies host network interface counters."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import platform
import shutil
import socket
import statistics
import subprocess
import sys
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import urlopen

TERMINAL = {"COMPLETED", "FAILED", "ABORTED"}
ROOT = Path(__file__).resolve().parents[1]


class NetworkMonitor:
    """Sample collector-host interfaces and TCP handshakes, never tensor payloads."""

    def __init__(self, targets):
        self.targets = targets
        self.previous = None
        try:
            import psutil

            self.provider = psutil
        except ImportError:
            self.provider = None

    def sample(self, directory):
        tick = time.monotonic()
        observation = {
            "observed_at": now(),
            "scope": "all traffic on collector host; not DTP-only",
            "interfaces": {},
            "tcp_probes": [],
            "counter_error": None,
        }
        if self.provider is None:
            observation["counter_error"] = "psutil unavailable; interface counters not measured"
        else:
            try:
                counters = self.provider.net_io_counters(pernic=True, nowrap=False)
                stats = self.provider.net_if_stats()
                previous_tick, previous = self.previous or (tick, {})
                interval = tick - previous_tick
                for name in sorted(counters.keys() | stats.keys()):
                    values = counters[name]._asdict() if name in counters else {}
                    old = previous.get(name)
                    reset = bool(old) and any(values.get(key, 0) < old[key] for key in old)
                    ready = bool(values and old) and interval > 0 and not reset
                    link = stats.get(name)
                    observation["interfaces"][name] = {
                        "is_up": link.isup if link else None,
                        "link_speed_mbps": (link.speed or None) if link else None,
                        "mtu": link.mtu if link else None,
                        "counters_since_os_reset": values,
                        "counter_reset_detected": reset,
                        "sample_interval_s": interval if old else None,
                        "tx_bytes_per_s": (values["bytes_sent"] - old["bytes_sent"]) / interval
                        if ready
                        else None,
                        "rx_bytes_per_s": (values["bytes_recv"] - old["bytes_recv"]) / interval
                        if ready
                        else None,
                    }
                self.previous = (tick, {name: value._asdict() for name, value in counters.items()})
            except Exception as exc:
                self.previous = None
                observation["counter_error"] = f"{type(exc).__name__}: {exc}"
        for host, port in self.targets:
            started = time.monotonic()
            probe = {"host": host, "port": port, "connected": False, "connect_ms": None}
            try:
                # Numeric address lookup is cheap; DNS names may add resolution time.
                with socket.create_connection((host, port), timeout=1):
                    probe["connected"] = True
                    probe["connect_ms"] = (time.monotonic() - started) * 1000
            except OSError as exc:
                probe["error"] = f"{type(exc).__name__}: {exc}"
            observation["tcp_probes"].append(probe)
        with (directory / "network.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(observation, ensure_ascii=False) + "\n")
        return observation


def network_targets(backend_url, extra):
    targets = []
    for value in [backend_url, *extra]:
        parsed = urlsplit(value if "://" in value else "//" + value)
        if not parsed.hostname:
            raise ValueError("Network targets require a host")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        target = (parsed.hostname, port)
        if target not in targets:
            targets.append(target)
    if len(targets) > 4:
        raise ValueError("At most four TCP probe targets are supported")
    return targets


def now():
    return datetime.now(UTC).isoformat()


def save_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest_stream(stream):
    digest = hashlib.sha256()
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def safe_id(value):
    # Filesystem paths never use identities supplied by an HTTP response directly.
    return hashlib.sha256(value.encode()).hexdigest()


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


class LocalArtifacts:
    """Read only published checkpoints and launcher logs; never read Node credentials."""

    def __init__(self, state_dir):
        self.root = state_dir.resolve()
        self.log_offsets = {}

    def attempt_directory(self, attempt_id):
        candidate = self.root / "checkpoints" / attempt_id
        if candidate.resolve().parent != self.root / "checkpoints" or candidate.is_symlink():
            raise ValueError("Unsafe local Attempt path")
        return candidate

    def inventory(self, attempt_id):
        directory = self.attempt_directory(attempt_id)
        if not directory.is_dir():
            return None  # No local Runtime files: fall back to API.
        items = []
        for folder in sorted(directory.iterdir()):
            if folder.name.startswith(".") or folder.is_symlink() or not folder.is_dir():
                continue
            metadata_path = folder / "checkpoint.json"
            model_path = folder / "model.bin"
            if not metadata_path.is_file() or not model_path.is_file():
                continue
            if metadata_path.is_symlink() or model_path.is_symlink():
                raise ValueError("Checkpoint symlinks are not supported")
            raw = metadata_path.read_bytes()
            metadata = json.loads(raw)
            if (
                metadata["created_by_attempt_id"] != attempt_id
                or folder.name != safe_id(metadata["checkpoint_id"])
                or raw != canonical_bytes(metadata)
            ):
                raise ValueError("Local checkpoint identity/canonical metadata mismatch")
            items.append(
                {
                    "checkpoint_id": metadata["checkpoint_id"],
                    "state": "COMPLETE",
                    "created_by_attempt_id": attempt_id,
                    "model_version": metadata["model"]["model_version"],
                    "integrity": {
                        "model_sha256": metadata["model"]["payload_sha256"],
                        "metadata_sha256": hashlib.sha256(raw).hexdigest(),
                    },
                }
            )
        return items

    def export(self, detail, contract, destination):
        directory = self.attempt_directory(detail["created_by_attempt_id"]) / safe_id(
            detail["checkpoint_id"]
        )
        metadata = json.loads((directory / "checkpoint.json").read_bytes())
        manifest = None
        for path in (self.root / "manifests").glob("*.json"):
            if path.is_symlink():
                continue
            candidate = json.loads(path.read_bytes())
            if (
                candidate.get("parameter_manifest_hash")
                == metadata["model"]["parameter_manifest_hash"]
            ):
                manifest = candidate
                break
        if manifest is None:
            raise FileNotFoundError("Matching local parameter manifest not found")
        temporary = destination.with_suffix(".part")
        try:
            with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as bundle:
                for filename in ("model.bin", "checkpoint.json"):
                    source = directory / filename
                    if source.is_symlink():
                        raise ValueError("Checkpoint symlink rejected")
                    bundle.write(source, filename)
                bundle.writestr("parameter-manifest.json", canonical_bytes(manifest))
                bundle.writestr("resolved-contract.json", canonical_bytes(contract))
            verify_export(temporary, detail)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)

    def logs(self, destination):
        log_dir = self.root / "logs"
        for source in log_dir.glob("*.log"):
            if source.is_symlink():
                continue
            # Preserve a bounded initial tail, then append new bytes once per poll.
            size = source.stat().st_size
            offset = self.log_offsets.get(source.name, max(0, size - 2 * 1024 * 1024))
            if size < offset:
                offset = 0
            with source.open("rb") as stream:
                stream.seek(offset)
                chunk = stream.read(1024 * 1024)
                self.log_offsets[source.name] = stream.tell()
            target = destination / "logs" / source.name
            target.parent.mkdir(exist_ok=True)
            with target.open("ab") as output:
                output.write(chunk)
        save_json(
            destination / "log-capture.json",
            {
                "source": "local launcher logs",
                "offsets": self.log_offsets,
                "note": (
                    "Initial tail <=2 MiB per file; older content omitted. "
                    "Shared service logs may include other runs."
                ),
            },
        )


class API:
    def __init__(self, base, timeout=30):
        self.base = base.rstrip("/")
        self.timeout = timeout

    def get(self, path, **query):
        suffix = "?" + urlencode(query) if query else ""
        with urlopen(self.base + path + suffix, timeout=self.timeout) as response:
            return json.load(response)

    def pages(self, path, **query):
        cursor = None
        seen = set()
        while True:
            page = self.get(path, limit=200, **query, **({"cursor": cursor} if cursor else {}))
            yield page
            cursor = page.get("page", {}).get("next_cursor")
            if not cursor:
                return
            if cursor in seen:
                raise ValueError("API pagination did not advance")
            seen.add(cursor)

    def download(self, path, destination):
        temporary = destination.with_suffix(".part")
        try:
            with (
                urlopen(self.base + path, timeout=self.timeout) as response,
                temporary.open("wb") as output,
            ):
                shutil.copyfileobj(response, output, length=1024 * 1024)
                expected = response.headers.get("Content-Length")
            if expected is not None and temporary.stat().st_size != int(expected):
                raise ValueError("Truncated model export")
            return temporary
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


def verify_export(path, detail):
    """Verify the checkpoint identities and bytes; never unpickle or extract ZIP paths."""
    with zipfile.ZipFile(path) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP entries")
        metadata_bytes = bundle.read("checkpoint.json")
        metadata = json.loads(metadata_bytes)
        integrity = detail["integrity"]
        if (
            hashlib.sha256(metadata_bytes).hexdigest() != integrity["metadata_sha256"]
            or metadata["checkpoint_id"] != detail["checkpoint_id"]
            or metadata["created_by_attempt_id"] != detail["created_by_attempt_id"]
        ):
            raise ValueError("Checkpoint metadata identity/hash mismatch")
        with bundle.open("model.bin") as stream:
            model_hash = digest_stream(stream)
        if (
            model_hash != integrity["model_sha256"]
            or model_hash != metadata["model"]["payload_sha256"]
            or bundle.getinfo("model.bin").file_size != metadata["model"]["payload_size_bytes"]
        ):
            raise ValueError("Model hash/size mismatch")
        contract = json.loads(bundle.read("resolved-contract.json"))
        canonical = canonical_bytes(contract)
        if hashlib.sha256(canonical).hexdigest() != metadata["contract_hash"]:
            raise ValueError("Resolved contract hash mismatch")
        manifest = json.loads(bundle.read("parameter-manifest.json"))
        expected_manifest = manifest.pop("parameter_manifest_hash")
        if (
            hashlib.sha256(canonical_bytes(manifest)).hexdigest() != expected_manifest
            or expected_manifest != metadata["model"]["parameter_manifest_hash"]
        ):
            raise ValueError("Parameter manifest hash mismatch")


def write_csv(path, rows, fields):
    with path.open("w", newline="", encoding="utf-8-sig") as output:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def seconds(start, end):
    if not start or not end:
        return None
    value = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    return value if value >= 0 else None


class Collector:
    def __init__(self, api, attempt_id, output, local=None, network=None):
        self.api = api
        self.attempt_id = attempt_id
        self.path = output / ("attempt-" + safe_id(attempt_id)[:20])
        self.path.mkdir(parents=True, exist_ok=True)
        self.endpoint = "/api/v1/attempts/" + quote(attempt_id, safe="")
        self.events = {}
        event_file = self.path / "events.jsonl"
        if event_file.exists():
            for line in event_file.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                self.events[row["runtime_event_seq"]] = row
        self.errors = {}
        self.exports = {}
        self.attempt = {}
        self.event_gap = False
        self.last_page_complete = False
        self.started_at = now()
        self.local = local
        self.network = network
        self.job = None
        self.workers = None
        # Keep verified copies even if Runtime retention removed the source after capture.
        for detail_file in (self.path / "checkpoints").glob("*/detail.json"):
            detail = json.loads(detail_file.read_bytes())
            identity = detail["checkpoint_id"]
            model = detail_file.parent / "model.zip"
            if (
                detail["created_by_attempt_id"] != attempt_id
                or detail_file.parent.name != safe_id(identity)
                or model.is_symlink()
                or detail_file.is_symlink()
            ):
                raise ValueError("Cached checkpoint identity/path mismatch")
            if model.is_file():
                try:
                    verify_export(model, detail)
                    self.exports[identity] = {
                        "checkpoint_id": identity,
                        "model_version": detail["model_version"],
                        "file": model.relative_to(self.path).as_posix(),
                        "source": "previous verified capture",
                    }
                except Exception as exc:
                    self.record_error("checkpoint:" + identity, exc)

    def record_error(self, key, exc):
        message = f"{type(exc).__name__}: {exc}"
        if self.errors.get(key) != message:
            print(f"[warning] {key}: {message}", flush=True)
        self.errors[key] = message

    def poll(self):
        if self.network:
            self.network.sample(self.path)
        if self.local:
            self.local.logs(self.path)
        self.attempt = self.api.get(self.endpoint)["data"]
        save_json(self.path / "attempt.json", self.attempt)
        if self.job is None:
            self.job = self.api.get("/api/v1/jobs/" + quote(self.attempt["job_id"], safe=""))[
                "data"
            ]
            save_json(self.path / "job.json", self.job)
        # Read after the contiguous prefix, so late lower sequences can still be recovered.
        after = 0
        while after + 1 in self.events:
            after += 1
        self.event_gap = False
        for page in self.api.pages(self.endpoint + "/events", after_seq=after):
            self.event_gap |= bool(page.get("meta", {}).get("gap_detected"))
            self.last_page_complete = bool(page.get("meta", {}).get("complete"))
            with (self.path / "events.jsonl").open("a", encoding="utf-8") as output:
                for event in page["data"]:
                    seq = event["runtime_event_seq"]
                    if seq not in self.events:
                        output.write(json.dumps(event, ensure_ascii=False) + "\n")
                    self.events[seq] = event
        self.errors.pop("poll", None)
        self.checkpoints()
        try:
            workers = self.workers
            if workers is None or self.attempt["state"] not in TERMINAL:
                workers = self.api.get(self.endpoint + "/workers")
                self.workers = workers
            save_json(self.path / "workers.json", workers)
            node_ids = {w.get("node_id") for w in workers["data"]} - {None}
            resources = {
                node: self.api.get("/api/v1/nodes/" + quote(node, safe=""))["data"]
                for node in sorted(node_ids)
            }
            with (self.path / "node-resources.jsonl").open("a", encoding="utf-8") as output:
                output.write(json.dumps({"observed_at": now(), "nodes": resources}) + "\n")
            self.errors.pop("node_resources", None)
        except Exception as exc:
            self.record_error("node_resources", exc)
        self.summarize(False)

    def checkpoints(self):
        inventory = self.local.inventory(self.attempt_id) if self.local else None
        local_inventory = inventory is not None
        if inventory is None:
            inventory = []
            for page in self.api.pages("/api/v1/checkpoints", attempt_id=self.attempt_id):
                inventory.extend(page["data"])
        save_json(self.path / "checkpoints.json", inventory)
        for checkpoint in inventory:
            if checkpoint["state"] != "COMPLETE":
                continue
            identity = checkpoint["checkpoint_id"]
            if identity in self.exports:
                continue
            try:
                export_source = "local files" if local_inventory else "Backend export API"
                endpoint = "/api/v1/checkpoints/" + quote(identity, safe="")
                detail = checkpoint if local_inventory else self.api.get(endpoint)["data"]
                folder = self.path / "checkpoints" / safe_id(identity)
                folder.mkdir(parents=True, exist_ok=True)
                save_json(folder / "detail.json", detail)
                model = folder / "model.zip"
                if identity not in self.exports:
                    if not model.exists():
                        if local_inventory:
                            try:
                                self.local.export(detail, self.job["resolved_contract"], model)
                            except FileNotFoundError:
                                export_source = "Backend export API (local manifest unavailable)"
                                temporary = self.api.download(endpoint + "/model", model)
                                try:
                                    verify_export(temporary, detail)
                                    temporary.replace(model)
                                finally:
                                    temporary.unlink(missing_ok=True)
                        else:
                            temporary = self.api.download(endpoint + "/model", model)
                            try:
                                verify_export(temporary, detail)
                                temporary.replace(model)
                            finally:
                                temporary.unlink(missing_ok=True)
                    else:
                        verify_export(model, detail)
                    self.exports[identity] = {
                        "checkpoint_id": identity,
                        "model_version": detail["model_version"],
                        "file": model.relative_to(self.path).as_posix(),
                        "source": export_source,
                    }
                    print(f"Saved verified model: {model}", flush=True)
                self.errors.pop("checkpoint:" + identity, None)
            except Exception as exc:
                self.record_error("checkpoint:" + identity, exc)
        # Retention or late projection must not silently hide a checkpoint we observed.
        expected = {
            event["details"]["checkpoint_id"]
            for event in self.events.values()
            if event["event_type"] == "checkpoint.saved"
        }
        missing = expected - self.exports.keys()
        if missing:
            self.errors["missing_checkpoints"] = (
                f"Observed checkpoints not archived: {sorted(missing)}"
            )
        else:
            self.errors.pop("missing_checkpoints", None)

    def summarize(self, finalized):
        ordered = [self.events[key] for key in sorted(self.events)]
        steps = {}
        epochs = []
        contributions = []
        async_progress = []
        for event in ordered:
            detail = event["details"]
            kind = event["event_type"]
            if kind == "epoch.metrics.finalized":
                epochs.append(detail)
            if kind == "async.progress":
                async_progress.append({"occurred_at": event["occurred_at"], **detail})
            if kind in {"step.started", "step.committed"}:
                row = steps.setdefault(detail["step_id"], {"step_id": detail["step_id"]})
                row.update(detail)
                if kind == "step.committed":
                    row["committed"] = True
            if kind == "model.updated":
                contributions.extend(
                    {"step_id": detail["step_id"], **item}
                    for item in detail.get("contributions", [])
                )
        committed = [row for row in steps.values() if row.get("committed")]
        for row in steps.values():
            row["duration_s"] = seconds(row.get("started_at"), row.get("committed_at"))
        elapsed = None
        if committed and all(
            row.get("started_at") and row.get("committed_at") for row in committed
        ):
            elapsed = seconds(
                min(row["started_at"] for row in committed),
                max(
                    [row["committed_at"] for row in committed]
                    + [
                        event["occurred_at"]
                        for event in ordered
                        if event["event_type"] == "checkpoint.saved"
                    ]
                ),
            )
        sample_counts = [row.get("total_sample_count") for row in committed]
        samples = sum(sample_counts) if sample_counts and None not in sample_counts else None
        durations = sorted(row["duration_s"] for row in committed if row["duration_s"] is not None)
        all_durations_present = bool(durations) and len(durations) == len(committed)
        seqs = sorted(self.events)
        contiguous = bool(seqs) and seqs == list(range(1, seqs[-1] + 1))
        reported_seq = (self.attempt.get("runtime") or {}).get("runtime_event_seq") or 0
        complete = (
            contiguous
            and not self.event_gap
            and self.last_page_complete
            and seqs[-1] >= reported_seq
        )
        summary = {
            "attempt_id": self.attempt_id,
            "state": self.attempt.get("state"),
            "training_strategy": self.attempt.get("training_strategy"),
            "collector_started_at": self.started_at,
            "updated_at": now(),
            "finalized": finalized,
            "event_history_complete": complete,
            "committed_steps_observed": len(committed),
            "committed_samples_observed": samples,
            "training_span_s": elapsed if complete else None,
            "samples_per_s": samples / elapsed if complete and samples and elapsed else None,
            "step_p50_s": statistics.median(durations)
            if complete and all_durations_present
            else None,
            "step_p95_s": durations[max(0, (95 * len(durations) + 99) // 100 - 1)]
            if complete and all_durations_present
            else None,
            "latest_epoch_metrics": epochs[-1] if epochs else None,
            "latest_async_progress": async_progress[-1] if async_progress else None,
            "model_exports": sorted(self.exports.values(), key=lambda x: x["model_version"]),
            "unresolved_errors": self.errors,
            "not_measured": [
                "validation/test quality",
                "F1/confusion matrix",
                "packet-level traffic",
            ],
            "notes": [
                "Training span: first committed step start through last commit/checkpoint event.",
                "Step latency: start to commit; epoch/final checkpoint time is in training span.",
                "No synthetic steps or sync throughput are computed for async.",
                "Node resources are sampled Agent snapshots, not all-host profiling.",
                "network.jsonl: host interface traffic and TCP checks; not DTP-only.",
                "Local logs: bounded initial tail, then append; datasets/source not copied.",
            ],
        }
        save_json(self.path / "summary.json", summary)
        save_json(self.path / "async-progress.json", async_progress)
        write_csv(
            self.path / "epochs.csv",
            epochs,
            ["epoch_index", "sample_count", "training_loss", "training_accuracy"],
        )
        write_csv(
            self.path / "steps.csv",
            steps.values(),
            [
                "step_id",
                "epoch",
                "batch_ordinal",
                "committed",
                "total_sample_count",
                "started_at",
                "update_completed_at",
                "synchronization_completed_at",
                "checkpoint_completed_at",
                "committed_at",
                "duration_s",
            ],
        )
        write_csv(
            self.path / "contributions.csv",
            contributions,
            ["step_id", "worker_id", "session_id", "sample_count", "loss", "compute_ms"],
        )
        return summary

    def archive(self):
        hashes = {}
        for path in sorted(self.path.rglob("*")):
            if path.is_file() and path.name != "sha256.json":
                with path.open("rb") as source:
                    hashes[path.relative_to(self.path).as_posix()] = digest_stream(source)
        save_json(self.path / "sha256.json", hashes)
        archive = shutil.make_archive(str(self.path), "zip", self.path)
        print(f"Send this archive: {archive}", flush=True)
        return archive


def discover(api, started, job_id=None):
    for page in api.pages("/api/v1/attempts", **({"job_id": job_id} if job_id else {})):
        for attempt in page["data"]:
            if (
                attempt["state"] not in TERMINAL
                or datetime.fromisoformat(attempt["created_at"]) >= started
            ):
                return attempt["attempt_id"]
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend-url", default=os.getenv("BACKEND_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--attempt-id", help="Export a specific current or past Attempt")
    parser.add_argument("--job-id", help="Restrict automatic detection to a Job")
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path(os.getenv("PBL4_STATE_DIR", str(ROOT / "var"))),
        help="Local launcher state directory (checkpoints, manifests, logs)",
    )
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "training-runs")
    parser.add_argument("--poll-seconds", type=float, default=5)
    parser.add_argument(
        "--network-target",
        action="append",
        default=[],
        metavar="HOST:PORT",
        help="Additional TCP reachability target (default probe: Backend)",
    )
    parser.add_argument("--no-network", action="store_true", help="Disable host network sampling")
    parser.add_argument("--settle-seconds", type=float, default=20)
    parser.add_argument("--finalize-timeout", type=float, default=120)
    args = parser.parse_args(argv)
    if (
        args.poll_seconds <= 0
        or args.settle_seconds < 0
        or args.finalize_timeout < args.settle_seconds
    ):
        parser.error("poll > 0 and finalize-timeout >= settle-seconds >= 0 are required")
    api = API(args.backend_url)
    try:
        network = (
            None
            if args.no_network
            else NetworkMonitor(network_targets(args.backend_url, args.network_target))
        )
    except ValueError as exc:
        parser.error(str(exc))
    started = datetime.now(UTC)
    collector = None
    terminal_since = None
    stable_since = time.monotonic()
    fingerprint = None
    print(
        f"Watching {api.base}; start training normally. Ctrl+C saves partial results.", flush=True
    )
    try:
        while True:
            try:
                if collector is None:
                    identity = args.attempt_id or discover(api, started, args.job_id)
                    if identity:
                        collector = Collector(
                            api, identity, args.output, LocalArtifacts(args.state_dir), network
                        )
                        print(f"Detected Attempt: {identity}", flush=True)
                        try:
                            revision = subprocess.check_output(
                                ["git", "rev-parse", "HEAD"],
                                cwd=ROOT,
                                text=True,
                                stderr=subprocess.DEVNULL,
                                timeout=5,
                            ).strip()
                        except (OSError, subprocess.SubprocessError):
                            revision = None
                        save_json(
                            collector.path / "collector-environment.json",
                            {
                                "python": sys.version,
                                "platform": platform.platform(),
                                "collector_checkout_commit": revision,
                                "note": "Collector machine only; remote Worker revision unknown.",
                            },
                        )
                if collector is not None:
                    collector.poll()
                    tick = time.monotonic()
                    current = (len(collector.events), len(collector.exports))
                    if current != fingerprint:
                        fingerprint, stable_since = current, tick
                    if collector.attempt.get("state") in TERMINAL:
                        if terminal_since is None:
                            terminal_since = tick
                        summary = collector.summarize(False)
                        latest = (collector.attempt.get("checkpoint") or {}).get(
                            "latest_checkpoint_id"
                        )
                        artifacts_ready = bool(collector.exports) and (
                            not latest or latest in collector.exports
                        )
                        ready = (
                            summary["event_history_complete"]
                            and artifacts_ready
                            and not collector.errors
                        )
                        expired = tick - terminal_since >= args.finalize_timeout
                        if (ready and tick - stable_since >= args.settle_seconds) or expired:
                            if not artifacts_ready:
                                collector.errors["model_export"] = (
                                    "No verified latest model export available"
                                )
                            collector.summarize(True)
                            collector.archive()
                            return 0 if ready else 2
            except Exception as exc:
                if collector is not None:
                    if collector.attempt.get("state") in TERMINAL and terminal_since is None:
                        terminal_since = time.monotonic()
                    collector.record_error("poll", exc)
                    collector.summarize(False)
                    if (
                        terminal_since is not None
                        and time.monotonic() - terminal_since >= args.finalize_timeout
                    ):
                        collector.archive()
                        return 2
                else:
                    print(f"Waiting for Backend: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        if collector is not None:
            collector.errors["interrupted"] = "Collector stopped by user; capture may be incomplete"
            collector.summarize(False)
            collector.archive()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
