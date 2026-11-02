"""Real artifact/HTTP/model roundtrips and corruption/cleanup coverage."""

import json
import zipfile
from dataclasses import replace

import httpx
import numpy as np
import pytest

from pbl4.common.hashing import canonical_json_hash
from pbl4.common.model_profiles import MODEL_PROFILES
from pbl4.runtime.artifact_http import ArtifactHTTP
from pbl4.runtime.batch_scheduler import RecoveryCursor
from pbl4.runtime.canonical_model import ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointManager
from pbl4.runtime.checkpoint_artifacts import CheckpointArtifacts
from pbl4.runtime.checkpoint_v1 import CheckpointV1Serializer
from pbl4.runtime.snapshot import CheckpointSnapshot


def make_artifact(root, model_id="small_cnn", checkpoint_id="checkpoint", version=1):
    torch = pytest.importorskip("torch")
    from pbl4.adapter.models.factory import build_model
    from pbl4.adapter.pytorch_adapter import PyTorchAdapter

    model = build_model(model_id, initialization_seed=42)
    # Distinct from factory initialization: verify actual saved weights are restored.
    with torch.no_grad():
        for parameter in model.parameters():
            parameter.add_(0.125)
    adapter = PyTorchAdapter(model, torch.nn.CrossEntropyLoss(), local_gradient_reduction="mean")
    contract = {"model": {"model_id": model_id}, "dataset": {"preprocessing": {}}}
    snapshot = CheckpointSnapshot(
        checkpoint_id=checkpoint_id,
        checkpoint_schema_version=1,
        job_id="job",
        created_by_attempt_id="attempt",
        contract_hash=canonical_json_hash(contract),
        checkpoint_policy="periodic",
        checkpoint_policy_version=1,
        training_strategy="strict_bsp",
        dataset_build_id="build",
        dataset_manifest_hash="a" * 64,
        model_id=model_id,
        model_profile=MODEL_PROFILES[model_id],
        source_operation_id=version,
        source_step_id=version,
        optimizer="plain_sgd",
        created_at=f"2026-11-02T00:00:{version:02d}Z",
        model=ModelSnapshot(
            version,
            adapter.manifest.parameter_manifest_hash,
            np.concatenate([a.reshape(-1) for a in adapter.export_parameters().tensors]).tobytes(),
        ),
        recovery_cursor=RecoveryCursor(version, 0),
    )
    manager = CheckpointManager.for_attempt(root, "attempt", CheckpointV1Serializer())
    saved = manager.write(snapshot)
    descriptor = {
        "checkpoint_id": checkpoint_id,
        "created_by_attempt_id": "attempt",
        "model_sha256": saved.model_sha256,
        "metadata_sha256": saved.metadata_sha256,
    }
    return CheckpointArtifacts(root, [adapter.manifest]), descriptor, contract, model, saved


@pytest.mark.parametrize("model_id", ["small_cnn", "resnet18_groupnorm"])
def test_export_restores_exact_weights_and_predictions(tmp_path, model_id):
    import torch

    from pbl4.adapter.model_export import load_exported_model

    owner, descriptor, contract, model, _ = make_artifact(tmp_path, model_id)
    import tracemalloc

    tracemalloc.start()
    with owner.export(descriptor, contract) as archive:
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        # Export memory must stay bounded even for the 44 MB reference model.
        assert peak < 8 * 1024 * 1024
        loaded = load_exported_model(archive)
        model.eval()
        for actual, expected in zip(loaded.parameters(), model.parameters(), strict=True):
            assert torch.equal(actual, expected)
        inputs = torch.zeros(1, 3, 32, 32)
        with torch.no_grad():
            assert torch.equal(loaded(inputs), model(inputs))
        temporary = archive
    assert not temporary.exists()


def test_inventory_pagination_excludes_partial_and_purge_is_pinned(tmp_path):
    owner, descriptor, contract, _, saved = make_artifact(tmp_path)
    manager = CheckpointManager(saved.directory.parent, CheckpointV1Serializer())
    manager.write(replace(saved.snapshot, checkpoint_id="second"))
    (saved.directory.parent / ".tmp-partial").mkdir()
    first = owner.inventory(limit=1)
    second = owner.inventory(first["next_cursor"], limit=1)
    assert len(first["items"]) == len(second["items"]) == 1
    assert first["items"][0]["checkpoint_id"] != second["items"][0]["checkpoint_id"]
    assert second["next_cursor"] is None
    with pytest.raises(ValueError):
        owner.purge({**descriptor, "model_sha256": "b" * 64})
    assert saved.directory.is_dir()
    with owner.export(descriptor, contract) as archive:
        owner.purge(descriptor)
        assert zipfile.is_zipfile(archive)  # Prepared export is independent of source deletion.
    owner.purge(descriptor)


def test_corruption_and_wrong_contract_are_rejected(tmp_path):
    owner, descriptor, contract, _, saved = make_artifact(tmp_path)
    with pytest.raises(ValueError, match="contract"), owner.export(descriptor, {"different": True}):
        pytest.fail("An invalid export was published")
    (saved.directory / "model.bin").write_bytes(b"corrupt")
    with pytest.raises(ValueError), owner.export(descriptor, contract):
        pytest.fail("A corrupt export was published")
    assert saved.directory.exists()


def test_http_auth_roundtrip_and_client_cleanup(tmp_path, monkeypatch):
    from pbl4.management_backend.clients.runtime_artifacts import RuntimeArtifacts

    owner, descriptor, contract, _, _ = make_artifact(tmp_path)
    server = ArtifactHTTP("127.0.0.1", 0, "test-token", owner)
    connections = []
    accept = server._server.get_request

    def counted_accept():
        connection = accept()
        connections.append(connection[1])
        return connection

    monkeypatch.setattr(server._server, "get_request", counted_accept)
    server.start()
    url = f"http://127.0.0.1:{server.address[1]}"
    try:
        assert httpx.get(url + "/inventory", trust_env=False).status_code == 401
        before = len(connections)
        with RuntimeArtifacts(url, "test-token") as client:
            assert len(list(client.inventory())) == 1
            with client.export(descriptor, contract) as response:
                output = tmp_path / "download.zip"
                output.write_bytes(b"".join(response.iter_bytes()))
            with zipfile.ZipFile(output) as archive:
                assert json.loads(archive.read("checkpoint.json"))["checkpoint_id"] == "checkpoint"
            client.purge(descriptor)
            client.purge(descriptor)
            assert list(client.inventory()) == []
        assert len(connections) - before == 1

    finally:
        server.stop()


def test_interrupted_http_export_closes_incomplete_zip_and_removes_temp(tmp_path, monkeypatch):
    import pbl4.runtime.artifact_http as artifact_http

    owner, descriptor, contract, _, _ = make_artifact(tmp_path)

    def interrupted_copy(_source, destination, **_kwargs):
        destination.write(b"PK")
        raise OSError("Simulated storage read failure")

    monkeypatch.setattr(artifact_http.shutil, "copyfileobj", interrupted_copy)
    server = ArtifactHTTP("127.0.0.1", 0, "test-token", owner)
    server.start()
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{server.address[1]}",
            headers={"Authorization": "Bearer test-token"},
            trust_env=False,
        ) as client:
            with pytest.raises(httpx.RemoteProtocolError):
                client.post("/export", json={"descriptor": descriptor, "contract": contract})
            assert client.get("/inventory").status_code == 200
        assert list((tmp_path / ".exports").iterdir()) == []
    finally:
        server.stop()


@pytest.mark.parametrize("attempt", ["..", "a/b", "a\\b"])
def test_path_escape_is_rejected(tmp_path, attempt):
    owner = CheckpointArtifacts(tmp_path, [])
    with pytest.raises(ValueError):
        owner.purge({"created_by_attempt_id": attempt, "checkpoint_id": "checkpoint"})


def test_partial_purge_can_be_retried_and_protected_ids_are_kept(tmp_path):
    owner, descriptor, _, _, saved = make_artifact(tmp_path)
    protected = CheckpointArtifacts(tmp_path, [], protected_ids=lambda: {"checkpoint"})
    with pytest.raises(ValueError, match="protected"):
        protected.purge(descriptor)
    assert saved.directory.exists()
    (saved.directory / "model.bin").unlink()
    owner.purge(descriptor)
    assert not saved.directory.exists()


def test_export_reaps_only_old_owned_temporary_directories(tmp_path):
    import os
    import time

    owner, descriptor, contract, _, _ = make_artifact(tmp_path)
    old = tmp_path / ".exports" / "export-abandoned"
    old.mkdir(parents=True)
    (old / "model.zip").write_bytes(b"incomplete")
    stamp = time.time() - 90000
    os.utime(old, (stamp, stamp))
    recent = old.parent / "export-recent"
    recent.mkdir()
    with owner.export(descriptor, contract) as archive:
        assert archive.is_file()
        assert not old.exists()
        assert recent.exists()
        assert len(owner.inventory()["items"]) == 1
    assert not archive.exists()


def test_inventory_cache_expires_and_file_changes_invalidate_it(tmp_path, monkeypatch):
    import os
    from unittest.mock import patch

    import pbl4.runtime.checkpoint_artifacts as artifacts

    owner, descriptor, contract, _, saved = make_artifact(tmp_path)
    clock = [1000.0]
    monkeypatch.setattr(artifacts.time, "monotonic", lambda: clock[0])
    with patch.object(artifacts, "sha256_file", wraps=artifacts.sha256_file) as hashing:
        assert len(owner.inventory()["items"]) == 1
        assert len(owner.inventory()["items"]) == 1
        assert hashing.call_count == 1
        clock[0] += 301
        assert len(owner.inventory()["items"]) == 1
        assert hashing.call_count == 2
        payload = saved.directory / "model.bin"
        stat = payload.stat()
        raw = bytearray(payload.read_bytes())
        raw[0] ^= 1
        payload.write_bytes(raw)
        os.utime(payload, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))
        with pytest.raises(ValueError, match="hash mismatch"), owner.export(descriptor, contract):
            pytest.fail("Export reused cached integrity instead of checking written bytes")
        assert owner.inventory()["items"] == []
        assert hashing.call_count == 3


def test_artifact_auth_reuses_root_identity_with_domain_separation(monkeypatch):
    from pbl4.common.artifact_origin import MODEL_ARTIFACT_PORT
    from pbl4.common.hashing import derive_model_artifact_token
    from pbl4.management_backend.config import BackendSettings

    monkeypatch.setenv("RUNTIME_ARTIFACT_TOKEN", "obsolete-override")
    monkeypatch.setenv("RUNTIME_ARTIFACT_PORT", "1")
    settings = BackendSettings(_env_file=None, PBL4_WORKER_ADMISSION_SECRET="existing-shared-key")
    assert not any(name.startswith("runtime_artifact") for name in BackendSettings.model_fields)
    assert settings.runtime_artifact_url.endswith(f":{MODEL_ARTIFACT_PORT}")
    assert settings.runtime_artifact_token == derive_model_artifact_token("existing-shared-key")
    # Keep the existing token bytes compatible when simplifying the call sites.
    assert settings.runtime_artifact_token == (
        "d293430fa1475be09d106af52ddd8b17c828de2e172e109eed0df33de759252a"
    )
    assert settings.runtime_artifact_token != "existing-shared-key"
    assert (
        BackendSettings(_env_file=None, PBL4_WORKER_ADMISSION_SECRET=None).runtime_artifact_token
        is None
    )
