"""Runtime and Worker HTTP provisioning clients verify identity and hash chains."""

import io
import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from pbl4.common.hashing import sha256_bytes
from pbl4.runtime.dataset_manifest_client import DatasetManifestClient
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.shard_downloader import ShardDownloader
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts


def artifacts(tmp_path):
    data = create_synthetic_dataset_artifacts(
        tmp_path / "dataset",
        dataset_build_id="download-build",
        shard_count=2,
        batches_per_shard=2,
        batch_size=2,
        input_shape=(3, 2, 2),
    )
    service_base = "http://dm"
    artifact_base = f"{service_base}/artifacts/v1/dataset-builds/{data.dataset_build_id}"
    responses = {
        f"{artifact_base}/manifest.json": data.root_manifest_bytes,
        f"{artifact_base}/shards/0/manifest.json": data.shard_manifest_bytes[0],
    }
    shard = data.shard_manifest_dicts[0]
    for entry in shard["batches"]:
        responses[f"{artifact_base}/shards/0/batches/{entry['batch_id']}"] = data.batch_bytes[
            entry["relative_filename"]
        ]
    key = ShardCacheKey(data.dataset_build_id, data.dataset_manifest_hash, shard_id=0)
    return service_base, artifact_base, responses, key, data.root_manifest_dict


class Response:
    status = 200

    def __init__(self, content: bytes, fail_after_first_read: bool = False):
        self._stream = io.BytesIO(content)
        self._fail = fail_after_first_read
        self._reads = 0

    def read(self, size=-1):
        self._reads += 1
        if self._fail and self._reads > 1:
            raise OSError("partial connection")
        return self._stream.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class Opener:
    def __init__(self, responses: dict[str, bytes], fail_first_url: str | None = None):
        self.responses = responses
        self.fail_first_url = fail_first_url
        self.calls: list[str] = []

    def __call__(self, request, **_kwargs):
        url = request.full_url
        self.calls.append(url)
        content = self.responses[url]
        fail = url == self.fail_first_url and self.calls.count(url) == 1
        return Response(content, fail_after_first_read=fail)


def test_runtime_pins_exact_root_manifest_and_rejects_wrong_hash(tmp_path):
    service_base, _, responses, key, root = artifacts(tmp_path)
    opener = Opener(responses)
    pinned = DatasetManifestClient(service_base, opener=opener).pin(
        key.dataset_build_id, key.dataset_manifest_hash
    )
    assert pinned.value == root
    assert pinned.shard_count == 2
    assert pinned.batch_count_per_shard == 2
    with pytest.raises(ValueError, match="hash mismatch"):
        DatasetManifestClient(service_base, opener=opener).pin(key.dataset_build_id, "0" * 64)


def test_worker_retries_partial_download_publishes_and_reuses_cache(tmp_path):
    _, artifact_base, responses, key, _ = artifacts(tmp_path)
    root_url = f"{artifact_base}/manifest.json"
    opener = Opener(responses, fail_first_url=root_url)
    cache = ShardCache(tmp_path / "cache")
    downloader = ShardDownloader(
        artifact_base,
        cache,
        tmp_path / "parts",
        chunk_size=17,
        opener=opener,
    )
    result = downloader.provision(key)
    assert not result.cache_reused
    assert result.bytes_downloaded > 0
    assert result.shard.load_batch(0)[0].shape == (2, 3, 2, 2)
    assert not list((tmp_path / "parts").glob("*.part"))
    calls = len(opener.calls)
    reused = downloader.provision(key)
    assert reused.cache_reused
    assert reused.bytes_downloaded == 0
    assert len(opener.calls) == calls


def test_worker_rejects_hash_mismatch_and_wrong_identity(tmp_path):
    _, artifact_base, responses, key, _ = artifacts(tmp_path)
    corrupt = dict(responses)
    batch_url = next(url for url in corrupt if "/batches/" in url)
    corrupt[batch_url] = b"corrupt"
    downloader = ShardDownloader(
        artifact_base,
        ShardCache(tmp_path / "cache"),
        tmp_path / "parts",
        retries=2,
        opener=Opener(corrupt),
    )
    with pytest.raises(ValueError, match="retry policy"):
        downloader.provision(key)
    with pytest.raises(ValueError, match="retry policy"):
        ShardDownloader(
            artifact_base,
            ShardCache(tmp_path / "wrong-cache"),
            tmp_path / "wrong-parts",
            retries=1,
            opener=Opener(responses),
        ).provision(ShardCacheKey(key.dataset_build_id, sha256_bytes(b"wrong"), 0))


def test_worker_rejects_artifact_base_for_another_build(tmp_path):
    _, artifact_base, responses, key, _ = artifacts(tmp_path)
    downloader = ShardDownloader(
        f"{artifact_base}-other",
        ShardCache(tmp_path / "cache"),
        tmp_path / "parts",
        opener=Opener(responses),
    )
    with pytest.raises(ValueError, match="does not match"):
        downloader.provision(key)


def test_concurrent_worker_publication_converges_on_one_cache_entry(tmp_path):
    _, artifact_base, responses, key, _ = artifacts(tmp_path)
    cache = ShardCache(tmp_path / "cache")
    downloaders = [
        ShardDownloader(
            artifact_base,
            cache,
            tmp_path / f"parts-{index}",
            opener=Opener(responses),
        )
        for index in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda downloader: downloader.provision(key), downloaders))
    assert {result.shard.directory for result in results} == {
        tmp_path / "cache" / key.directory_key
    }
    assert cache.load(key).load_batch(0)[0].shape == (2, 3, 2, 2)


@pytest.mark.parametrize(
    "fault", ["missing_batch", "wrong_batch_hash", "wrong_root_hash", "wrong_shard_hash"]
)
def test_worker_repairs_invalid_cache_without_redownloading_valid_batches(tmp_path, fault):
    _, artifact_base, responses, key, _ = artifacts(tmp_path)
    cache = ShardCache(tmp_path / "cache")
    opener = Opener(responses)
    downloader = ShardDownloader(artifact_base, cache, tmp_path / "parts", opener=opener)
    initial = downloader.provision(key)
    entry = initial.shard.shard_manifest["batches"][0]
    batch_path = initial.shard.directory / entry["relative_filename"]
    if fault == "missing_batch":
        batch_path.unlink()
    elif fault == "wrong_batch_hash":
        original = batch_path.read_bytes()
        batch_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    else:
        name = "dataset-manifest.json" if fault == "wrong_root_hash" else "shard-manifest.json"
        (initial.shard.directory / name).write_bytes(b"{}")
    opener.calls.clear()
    repaired = downloader.provision(key)
    assert not repaired.cache_reused
    batches = [url for url in opener.calls if "/batches/" in url]
    expected_batches = [f"{artifact_base}/shards/0/batches/0"] if "batch" in fault else []
    assert batches == expected_batches
    assert repaired.bytes_downloaded == sum(len(responses[url]) for url in opener.calls)
    cache.load(key).load_batch(0)
    opener.calls.clear()
    assert downloader.provision(key).cache_reused
    assert opener.calls == []
    assert not list((tmp_path / "cache" / ".part").iterdir())


def test_concurrent_repairs_converge_on_verified_entry(tmp_path):
    _, artifact_base, responses, key, _ = artifacts(tmp_path)
    cache = ShardCache(tmp_path / "cache")
    initial = ShardDownloader(
        artifact_base, cache, tmp_path / "parts", opener=Opener(responses)
    ).provision(key)
    (
        initial.shard.directory / initial.shard.shard_manifest["batches"][0]["relative_filename"]
    ).unlink()
    downloaders = [
        ShardDownloader(artifact_base, cache, tmp_path / f"repair-{i}", opener=Opener(responses))
        for i in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda d: d.provision(key), downloaders))
    assert len({r.shard.directory for r in results}) == 1
    cache.load(key).load_batch(0)


def test_different_manifest_identity_does_not_accept_or_remove_valid_cache(tmp_path):
    _, artifact_base, responses, key, _ = artifacts(tmp_path)
    cache = ShardCache(tmp_path / "cache")
    opener = Opener(responses)
    downloader = ShardDownloader(artifact_base, cache, tmp_path / "parts", retries=1, opener=opener)
    original = downloader.provision(key)
    wrong = ShardCacheKey(key.dataset_build_id, "f" * 64, key.shard_id)
    opener.calls.clear()
    with pytest.raises(ValueError, match="retry policy"):
        downloader.provision(wrong)
    assert opener.calls == [f"{artifact_base}/manifest.json"]
    assert cache.load(key).directory == original.shard.directory
    opener.calls.clear()
    assert downloader.provision(key).cache_reused
    assert opener.calls == []


def test_huggingface_artifact_urls_use_same_physical_cache_without_network_on_restart(tmp_path):
    _, local_base, local_responses, key, root = artifacts(tmp_path)
    base = f"https://huggingface.co/datasets/test/repo/resolve/main/dataset-builds/{key.dataset_build_id}"
    shard_bytes = local_responses[f"{local_base}/shards/0/manifest.json"]
    shard = json.loads(shard_bytes)
    responses = {
        f"{base}/dataset-manifest.json": local_responses[f"{local_base}/manifest.json"],
        f"{base}/{root['shards'][0]['relative_shard_manifest_path']}": shard_bytes,
        **{
            f"{base}/{entry['relative_filename']}": local_responses[
                f"{local_base}/shards/0/batches/{entry['batch_id']}"
            ]
            for entry in shard["batches"]
        },
    }
    opener = Opener(responses)
    first = ShardDownloader(
        base,
        ShardCache(tmp_path / "cache"),
        tmp_path / "parts",
        root_manifest_path="dataset-manifest.json",
        opener=opener,
    ).provision(key)
    assert not first.cache_reused
    assert set(opener.calls) == set(responses)

    def offline(*_args, **_kwargs):
        pytest.fail("Warm Worker must not contact Hugging Face")

    second = ShardDownloader(
        base,
        ShardCache(tmp_path / "cache"),
        tmp_path / "new-parts",
        root_manifest_path="dataset-manifest.json",
        opener=offline,
    ).provision(key)
    assert second.cache_reused and second.bytes_downloaded == 0
