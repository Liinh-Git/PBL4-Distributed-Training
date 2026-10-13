"""Production Runtime Work Unit catalog invariants."""

from pbl4.runtime.process import _AttemptRunner


def test_runtime_fetches_local_shard_using_http_route():
    import io
    from unittest.mock import patch

    from pbl4.common.hashing import canonical_json_bytes, sha256_bytes
    from pbl4.runtime.dataset_manifest_client import PinnedDatasetManifest

    raw = canonical_json_bytes(
        {"dataset_build_id": "build", "shard_id": 0, "batch_count": 1, "batches": []}
    )
    root = PinnedDatasetManifest(
        "build",
        "a" * 64,
        {
            "batch_count_per_shard": 1,
            "shards": [
                {
                    "shard_id": 0,
                    "relative_shard_manifest_path": "shards/000/shard-manifest.json",
                    "shard_manifest_sha256": sha256_bytes(raw),
                }
            ],
        },
        "http://localhost/artifacts/v1/dataset-builds/build",
        "manifest.json",
    )
    with patch("urllib.request.urlopen", return_value=io.BytesIO(raw)) as opened:
        _AttemptRunner.__new__(_AttemptRunner)._fetch_shard_manifests(root)
    assert opened.call_args.args[0].endswith("/shards/0/manifest.json")


def test_short_physical_batch_is_not_an_eligible_work_unit() -> None:
    manifests = (
        {
            "shard_id": 0,
            "batches": [
                {"batch_id": 0, "sample_count": 32},
                {"batch_id": 1, "sample_count": 17},
            ],
        },
        {
            "shard_id": 1,
            "batches": [
                {"batch_id": 0, "sample_count": 32},
                {"batch_id": 1, "sample_count": 32},
            ],
        },
    )

    units = _AttemptRunner._extract_work_units(manifests, unit_size=32)

    assert [(unit.shard_id, unit.batch_id) for unit in units] == [(0, 0), (1, 0), (1, 1)]
    assert all(unit.sample_count == 32 for unit in units)
