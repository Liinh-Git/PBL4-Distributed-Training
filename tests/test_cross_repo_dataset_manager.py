"""Cross-repository real HTTP integration tests between PBL4 and standalone Dataset Manager."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest

from pbl4.management_backend.clients.dataset_manager import DatasetManagerClient
from pbl4.runtime.dataset_manifest_client import DatasetManifestClient
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.shard_downloader import ShardDownloader


@pytest.fixture(scope="module")
def standalone_service():
    r"""Start the standalone Dataset Manager service from d:\Dataset-Manager."""
    dm_root = Path("d:/Dataset-Manager").resolve()
    python_exe = dm_root / ".venv" / "Scripts" / "python.exe"
    smoke_script = dm_root / "scripts" / "run_smoke_server.py"

    assert python_exe.exists(), f"Standalone python not found at {python_exe}"
    assert smoke_script.exists(), f"Smoke server script not found at {smoke_script}"

    proc = subprocess.Popen(
        [str(python_exe), str(smoke_script)],
        cwd=str(dm_root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = "http://127.0.0.1:9200"
    client = DatasetManagerClient(base_url)

    # Wait for server ready
    ready = False
    for _ in range(50):
        try:
            if client.check_health() == "healthy":
                ready = True
                break
        except Exception:
            pass
        time.sleep(0.1)

    if not ready:
        proc.kill()
        out, err = proc.communicate()
        raise RuntimeError(f"Standalone server failed to start: stdout={out!r}, stderr={err!r}")

    yield base_url, client

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def test_cross_repo_backend_runtime_worker_flow(standalone_service, tmp_path):
    """Exercise Backend, Runtime, and Worker clients against standalone Dataset Manager."""
    base_url, backend_client = standalone_service

    # A. Management Backend DatasetManagerClient: Health
    assert backend_client.check_health() == "healthy"

    # A. Management Backend DatasetManagerClient: Create Build
    import uuid

    cmd_id = f"cmd-xrepo-{uuid.uuid4().hex[:8]}"
    idemp_key = f"idemp-xrepo-{uuid.uuid4().hex[:8]}"
    source = {"type": "cifar10_download", "dataset_name": "cifar10", "version": "binary-v1"}
    normalization = {"mean": [0.5, 0.5, 0.5], "std": [0.5, 0.5, 0.5]}
    sub = backend_client.create_build(
        source=source,
        profile="CNN_IMAGE_CLASSIFICATION_V1",
        input_shape=[3, 32, 32],
        normalization=normalization,
        batch_size=2,
        shard_count=3,
        partition_seed=42,
        command_id=cmd_id,
        idempotency_key=idemp_key,
    )
    build_id = sub["dataset_build_id"]
    assert sub["state"] in ("CREATED", "QUEUED", "IMPORTING", "REGISTERING", "READY")

    # Poll status until REGISTERING
    start = time.time()
    st = backend_client.get_build(build_id)
    while time.time() - start < 10:
        if st["state"] in ("REGISTERING", "READY"):
            break
        time.sleep(0.1)
        st = backend_client.get_build(build_id)

    assert st["state"] == "REGISTERING"
    manifest_hash = st["dataset_manifest_hash"]
    manifest_uri = st["manifest_uri"]
    artifact_base_url = st["artifact_base_url"]

    # Verify PUBLIC_BASE_URL resolution
    assert manifest_uri == f"{base_url}/artifacts/v1/dataset-builds/{build_id}/manifest.json"
    assert artifact_base_url == f"{base_url}/artifacts/v1/dataset-builds/{build_id}"

    # A. Management Backend: Authoritative Registration ACK
    ack = backend_client.registration_ack(
        build_id,
        dataset_manifest_hash=manifest_hash,
        registration_id="reg-xrepo-123",
        catalog_persisted_at="2026-09-11T12:00:00Z",
    )
    assert ack["state"] == "READY"

    # B. Runtime DatasetManifestClient: Pin Root Manifest
    runtime_client = DatasetManifestClient(base_url)
    pinned = runtime_client.pin(build_id, manifest_hash)
    assert pinned.dataset_build_id == build_id
    assert pinned.dataset_manifest_hash == manifest_hash
    assert pinned.shard_count == 3
    assert pinned.batch_count_per_shard > 0

    # C. Worker ShardDownloader: Download & Cache Shard
    cache = ShardCache(tmp_path / "worker_cache")
    downloader = ShardDownloader(
        artifact_base_url=artifact_base_url,
        cache=cache,
        temporary_root=tmp_path / "worker_temp",
    )
    key = ShardCacheKey(build_id, manifest_hash, shard_id=0)
    result = downloader.provision(key)
    assert result.shard.key == key
    assert not result.cache_reused
    assert result.bytes_downloaded > 0

    # Load batch offline to verify arrays
    x, y, sample_ids = result.shard.load_batch(0)
    assert x.shape == (2, 3, 2, 2)
    assert len(y) == 2
    assert len(sample_ids) == 2

    # Second provision uses cache
    result2 = downloader.provision(key)
    assert result2.cache_reused is True
    assert result2.bytes_downloaded == 0

    # A. Management Backend: Rebuild, Deprecate, Purge
    rebuild = backend_client.rebuild(
        source_dataset_build_id=build_id,
        command_id="cmd-xrepo-rebuild",
        idempotency_key="idemp-xrepo-rebuild",
        batch_size=3,
    )
    assert rebuild["new_dataset_build_id"] != build_id

    deprecate = backend_client.deprecate(build_id, reason="test deprecation")
    assert deprecate["state"] == "DEPRECATED"

    purge = backend_client.purge(build_id, command_id="cmd-xrepo-purge")
    assert purge["state"] == "DELETED"
