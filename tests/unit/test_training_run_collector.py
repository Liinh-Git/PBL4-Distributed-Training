"""Read-only collection: real HTTP pagination, local artifacts and integrity failures."""

import hashlib
import importlib.util
import io
import json
import threading
import zipfile
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "collect_training_run.py"
spec = importlib.util.spec_from_file_location("training_run_collector", SCRIPT)
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


@pytest.fixture
def artifacts(tmp_path):
    payload = b"\x00\x00\x80\x3f"
    manifest = {"schema_version": 1, "total_numel": 1, "total_bytes": 4, "parameters": []}
    manifest_hash = hashlib.sha256(collector.canonical_bytes(manifest)).hexdigest()
    manifest["parameter_manifest_hash"] = manifest_hash
    contract = {"model": {"model_id": "small_cnn"}, "training": {"epochs": 1}}
    metadata = {
        "checkpoint_id": "cp-1",
        "created_by_attempt_id": "attempt-1",
        "contract_hash": hashlib.sha256(collector.canonical_bytes(contract)).hexdigest(),
        "model": {
            "model_version": 1,
            "payload_sha256": hashlib.sha256(payload).hexdigest(),
            "payload_size_bytes": 4,
            "parameter_manifest_hash": manifest_hash,
        },
    }
    raw = collector.canonical_bytes(metadata)
    detail = {
        "checkpoint_id": "cp-1",
        "created_by_attempt_id": "attempt-1",
        "state": "COMPLETE",
        "model_version": 1,
        "integrity": {
            "model_sha256": hashlib.sha256(payload).hexdigest(),
            "metadata_sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, value in {
            "model.bin": payload,
            "checkpoint.json": raw,
            "parameter-manifest.json": collector.canonical_bytes(manifest),
            "resolved-contract.json": collector.canonical_bytes(contract),
        }.items():
            archive.writestr(name, value)
    state = tmp_path / "state"
    folder = state / "checkpoints" / "attempt-1" / collector.safe_id("cp-1")
    folder.mkdir(parents=True)
    (folder / "checkpoint.json").write_bytes(raw)
    (folder / "model.bin").write_bytes(payload)
    (state / "manifests").mkdir()
    (state / "manifests" / "small_cnn.json").write_bytes(collector.canonical_bytes(manifest))
    (state / "logs").mkdir()
    (state / "logs" / "runtime.log").write_bytes(b"initial log\n")
    (state / ".env").write_text("DO_NOT_COLLECT=secret")
    return {
        "state": state,
        "folder": folder,
        "detail": detail,
        "contract": contract,
        "bundle": stream.getvalue(),
    }


def event(seq, kind, details):
    return {
        "runtime_event_seq": seq,
        "event_type": kind,
        "details": details,
        "occurred_at": "2026-11-14T00:00:04+00:00",
    }


class FakeAPI:
    def __init__(self, data):
        self.artifacts = data
        self.events = [
            event(1, "step.started", {"step_id": 0, "started_at": "2026-11-14T00:00:00+00:00"}),
            event(
                2,
                "step.committed",
                {
                    "step_id": 0,
                    "total_sample_count": 16,
                    "committed_at": "2026-11-14T00:00:02+00:00",
                },
            ),
            event(
                3,
                "epoch.metrics.finalized",
                {
                    "epoch_index": 0,
                    "sample_count": 16,
                    "training_loss": 0.5,
                    "training_accuracy": 75,
                },
            ),
            event(4, "checkpoint.saved", {"checkpoint_id": "cp-1"}),
        ]
        self.calls = []
        self.gap = False

    def get(self, path, **query):
        self.calls.append((path, query))
        if path == "/api/v1/attempts/attempt-1":
            return {
                "data": {
                    "attempt_id": "attempt-1",
                    "job_id": "job-1",
                    "state": "COMPLETED",
                    "training_strategy": "strict_bsp",
                    "runtime": {
                        "runtime_event_seq": max(e["runtime_event_seq"] for e in self.events)
                    },
                    "checkpoint": {"latest_checkpoint_id": "cp-1"},
                }
            }
        if path == "/api/v1/jobs/job-1":
            return {"data": {"resolved_contract": self.artifacts["contract"]}}
        if path.endswith("/workers"):
            return {"data": []}
        if path == "/api/v1/checkpoints/cp-1":
            return {"data": self.artifacts["detail"]}
        if path.endswith("/events"):
            after = max(int(query.get("after_seq", 0)), int(query.get("cursor", 0)))
            rows = [e for e in self.events if e["runtime_event_seq"] > after]
            page = rows[:200]
            more = len(rows) > 200
            return {
                "data": page,
                "page": {"next_cursor": str(page[-1]["runtime_event_seq"]) if more else None},
                "meta": {"complete": not more and not self.gap, "gap_detected": self.gap},
            }
        if path == "/api/v1/checkpoints":
            return {"data": [self.artifacts["detail"]], "page": {"next_cursor": None}}
        raise AssertionError(f"Unexpected API call: {path}")

    def pages(self, path, **query):
        yield self.get(path, **query)

    def download(self, path, destination):
        self.calls.append((path, {}))
        temporary = destination.with_suffix(".part")
        temporary.write_bytes(self.artifacts["bundle"])
        return temporary


def test_local_first_no_checkpoint_requests_and_logs_append(tmp_path, artifacts):
    api = FakeAPI(artifacts)
    run = collector.Collector(
        api, "attempt-1", tmp_path / "output", collector.LocalArtifacts(artifacts["state"])
    )
    run.poll()
    with (artifacts["state"] / "logs" / "runtime.log").open("ab") as output:
        output.write(b"new log\n")
    run.poll()
    assert not any(path.startswith("/api/v1/checkpoints") for path, _ in api.calls)
    assert (run.path / "logs" / "runtime.log").read_bytes() == b"initial log\nnew log\n"
    assert len((run.path / "events.jsonl").read_text().splitlines()) == 4
    summary = run.summarize(True)
    assert summary["training_span_s"] == 4  # Includes checkpoint after last commit.
    assert summary["samples_per_s"] == 4
    assert summary["model_exports"][0]["source"] == "local files"
    assert [q["after_seq"] for p, q in api.calls if p.endswith("/events")] == [0, 4]
    assert sum(p == "/api/v1/jobs/job-1" for p, _ in api.calls) == 1
    with zipfile.ZipFile(run.archive()) as archive:
        assert "sha256.json" in archive.namelist()
        assert not any(".env" in name for name in archive.namelist())


def test_remote_fallback_and_restart_does_not_duplicate_events(tmp_path, artifacts):
    api = FakeAPI(artifacts)
    run = collector.Collector(
        api, "attempt-1", tmp_path, collector.LocalArtifacts(tmp_path / "absent")
    )
    run.poll()
    again = collector.Collector(api, "attempt-1", tmp_path)
    again.poll()
    assert len((run.path / "events.jsonl").read_text().splitlines()) == 4
    assert sum(p.endswith("/model") for p, _ in api.calls) == 1


def test_late_sequence_is_recovered_and_missing_history_has_no_throughput(tmp_path, artifacts):
    api = FakeAPI(artifacts)
    late = api.events.pop(1)
    api.gap = True
    run = collector.Collector(api, "attempt-1", tmp_path)
    run.poll()
    assert run.summarize(False)["samples_per_s"] is None
    api.events.insert(1, late)
    api.gap = False
    run.poll()
    assert run.summarize(False)["event_history_complete"]
    assert run.summarize(False)["samples_per_s"] == 4


def test_corrupt_local_weights_are_not_accepted(tmp_path, artifacts):
    (artifacts["folder"] / "model.bin").write_bytes(b"evil")
    run = collector.Collector(
        FakeAPI(artifacts), "attempt-1", tmp_path, collector.LocalArtifacts(artifacts["state"])
    )
    run.poll()
    assert not run.exports
    assert "checkpoint:cp-1" in run.errors
    assert not list(run.path.rglob("*.part"))


@pytest.mark.parametrize("entry", ["checkpoint.json", "parameter-manifest.json", "model.bin"])
def test_corrupt_remote_export_is_rejected(tmp_path, artifacts, entry):
    path = tmp_path / "model.zip"
    with (
        zipfile.ZipFile(io.BytesIO(artifacts["bundle"])) as source,
        zipfile.ZipFile(path, "w") as target,
    ):
        for name in source.namelist():
            target.writestr(name, b"{}" if name == entry else source.read(name))
    with pytest.raises((ValueError, KeyError)):
        collector.verify_export(path, artifacts["detail"])


def test_missing_manifest_uses_existing_export_api(tmp_path, artifacts):
    (artifacts["state"] / "manifests" / "small_cnn.json").unlink()
    api = FakeAPI(artifacts)
    run = collector.Collector(
        api, "attempt-1", tmp_path, collector.LocalArtifacts(artifacts["state"])
    )
    run.poll()
    assert len(run.exports) == 1
    assert any(p.endswith("/model") for p, _ in api.calls)


def test_discovery_skips_old_terminal_but_attaches_active(artifacts):
    class Discovery:
        def pages(self, *args, **kwargs):
            yield {
                "data": [
                    {
                        "attempt_id": "old",
                        "state": "COMPLETED",
                        "created_at": "2020-01-01T00:00:00Z",
                    },
                    {
                        "attempt_id": "active",
                        "state": "RUNNING",
                        "created_at": "2020-01-01T00:00:00Z",
                    },
                ]
            }

    assert collector.discover(Discovery(), datetime.now(UTC)) == "active"


def test_real_http_pagination_download_and_final_archive(tmp_path, artifacts):
    fake = FakeAPI(artifacts)
    fake.events.extend(
        event(i, "epoch.metrics.finalized", {"epoch_index": i}) for i in range(5, 206)
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
            payload = (
                artifacts["bundle"]
                if parsed.path.endswith("/model")
                else json.dumps(fake.get(parsed.path, **query)).encode()
            )
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            collector.API(f"http://127.0.0.1:{server.server_port}").get(
                "/api/v1/attempts/attempt-1"
            )
        except URLError as exc:
            if isinstance(exc.reason, PermissionError):
                pytest.skip(f"Loopback sockets unavailable in sandbox: {exc.reason}")
            raise
        result = collector.main(
            [
                "--backend-url",
                f"http://127.0.0.1:{server.server_port}",
                "--attempt-id",
                "attempt-1",
                "--output",
                str(tmp_path / "out"),
                "--state-dir",
                str(tmp_path / "remote"),
                "--settle-seconds",
                "0",
            ]
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert result == 0
    archive_path = next((tmp_path / "out").glob("*.zip"))
    with zipfile.ZipFile(archive_path) as archive:
        summary = json.loads(archive.read("summary.json"))
        assert summary["event_history_complete"]
        assert summary["finalized"]
        assert len(archive.read("events.jsonl").splitlines()) == 205
        assert summary["model_exports"]


def test_local_path_traversal_rejected(tmp_path):
    local = collector.LocalArtifacts(tmp_path)
    with pytest.raises(ValueError, match="Unsafe"):
        local.inventory("../../outside")


def test_local_production_checkpoint_bundle_loads_exact_inference_model(tmp_path):
    torch = pytest.importorskip("torch")
    from pbl4.adapter.model_export import load_exported_model
    from tests.unit.test_checkpoint_artifacts import make_artifact

    state = tmp_path / "state"
    owner, _, contract, original, _ = make_artifact(state / "checkpoints")
    manifests = state / "manifests"
    manifests.mkdir()
    manifest = next(iter(owner._manifests.values()))
    (manifests / "model.json").write_bytes(collector.canonical_bytes(manifest.to_dict()))
    local = collector.LocalArtifacts(state)
    detail = local.inventory("attempt")[0]
    destination = tmp_path / "model.zip"
    local.export(detail, contract, destination)
    loaded = load_exported_model(destination)
    original.eval()
    with torch.inference_mode():
        inputs = torch.zeros(1, 3, 32, 32)
        assert torch.equal(loaded(inputs), original(inputs))


def test_restart_preserves_archived_model_after_source_retention(tmp_path, artifacts):
    api = FakeAPI(artifacts)
    local = collector.LocalArtifacts(artifacts["state"])
    run = collector.Collector(api, "attempt-1", tmp_path / "out", local)
    run.poll()
    for path in artifacts["folder"].iterdir():
        path.unlink()
    artifacts["folder"].rmdir()
    resumed = collector.Collector(api, "attempt-1", tmp_path / "out", local)
    resumed.poll()
    assert resumed.exports["cp-1"]["source"] == "previous verified capture"
    assert not resumed.errors


def test_retired_checkpoint_is_reported_and_async_does_not_invent_steps(tmp_path, artifacts):
    api = FakeAPI(artifacts)
    run = collector.Collector(api, "attempt-1", tmp_path)
    run.poll()
    api.events.append(event(5, "checkpoint.saved", {"checkpoint_id": "retired"}))
    run.poll()
    assert "retired" in run.errors["missing_checkpoints"]
    run.events = {1: event(1, "async.progress", {"processed_samples": 48, "applied_samples": 32})}
    run.attempt["training_strategy"] = "async_sgd"
    run.attempt["runtime"]["runtime_event_seq"] = 1
    summary = run.summarize(False)
    assert summary["event_history_complete"]
    assert summary["committed_steps_observed"] == 0
    assert summary["samples_per_s"] is None
    assert summary["latest_async_progress"]["processed_samples"] == 48
