"""Runtime and Worker HTTP provisioning clients verify identity and hash chains."""

import io
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from pbl4.common.hashing import sha256_bytes
from pbl4.dataset_manager.config import DatasetBuildConfig
from pbl4.dataset_manager.preprocessing import Preprocessor
from pbl4.dataset_manager.storage import DatasetStorage
from pbl4.runtime.dataset_manifest_client import DatasetManifestClient
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.shard_downloader import ShardDownloader


def artifacts(tmp_path):
    config = DatasetBuildConfig(
        1,
        "download-build",
        "cifar10",
        "CIFAR-10",
        "CNN_IMAGE_CLASSIFICATION_V1",
        "image_classification",
        (3, 2, 2),
        "float32",
        10,
        {
            "channel_order": "NCHW",
            "scale": "uint8_to_unit",
            "mean": [0.5, 0.5, 0.5],
            "std": [0.5, 0.5, 0.5],
        },
        2,
        2,
        "seeded_permutation_round_robin",
        42,
    )
    raw = np.arange(8 * 12, dtype=np.uint8).reshape(8, 3, 2, 2)
    samples = Preprocessor((3, 2, 2), 10, (0.5,) * 3, (0.5,) * 3).transform(
        raw, np.arange(8, dtype=np.int64)
    )
    published = DatasetStorage(tmp_path / "dataset").materialize(config, samples)
    root = json.loads(published.manifest_path.read_bytes())
    reference = root["shards"][0]
    shard_path = published.directory / reference["relative_shard_manifest_path"]
    shard = json.loads(shard_path.read_bytes())
    service_base = "http://dm"
    artifact_base = f"{service_base}/artifacts/v1/dataset-builds/{published.dataset_build_id}"
    responses = {
        f"{artifact_base}/manifest.json": published.manifest_path.read_bytes(),
        f"{artifact_base}/shards/0/manifest.json": shard_path.read_bytes(),
    }
    for entry in shard["batches"]:
        responses[f"{artifact_base}/shards/0/batches/{entry['batch_id']}"] = (
            published.directory / entry["relative_filename"]
        ).read_bytes()
    key = ShardCacheKey(published.dataset_build_id, published.dataset_manifest_hash, shard_id=0)
    return service_base, artifact_base, responses, key, root


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
