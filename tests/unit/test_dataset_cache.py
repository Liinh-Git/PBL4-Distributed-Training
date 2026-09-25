"""Unit tests for worker DatasetCache container (Task T3.1)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from pbl4.common.work_unit import WorkUnitRef
from pbl4.worker.dataset_cache import DatasetCache
from pbl4.worker.shard_cache import CachedShard, ShardCache, ShardCacheKey
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts


@pytest.fixture
def multi_shard_data(tmp_path: Path):
    dest = tmp_path / "artifacts"
    artifacts = create_synthetic_dataset_artifacts(
        destination_dir=dest,
        dataset_build_id="build-test-dataset-cache",
        shard_count=3,
        batches_per_shard=2,
        batch_size=4,
        input_shape=(3, 2, 2),
    )
    cache = ShardCache(tmp_path / "cache")
    cached_shards: dict[int, CachedShard] = {}
    for s_id in range(3):
        key = ShardCacheKey(
            artifacts.dataset_build_id, artifacts.dataset_manifest_hash, shard_id=s_id
        )
        cached = cache.publish(
            key,
            artifacts.root_manifest_bytes,
            artifacts.shard_manifest_bytes[s_id],
            artifacts.shard_batch_bytes[s_id],
        )
        cached_shards[s_id] = cached
    return artifacts, cached_shards


def test_dataset_cache_creation_and_properties(multi_shard_data):
    artifacts, cached_shards = multi_shard_data
    cache = DatasetCache(
        dataset_build_id=artifacts.dataset_build_id,
        dataset_manifest_hash=artifacts.dataset_manifest_hash,
        shards=cached_shards,
    )

    assert cache.dataset_build_id == artifacts.dataset_build_id
    assert cache.dataset_manifest_hash == artifacts.dataset_manifest_hash
    assert cache.shard_count == 3
    assert len(cache) == 3
    assert 0 in cache
    assert 1 in cache
    assert 2 in cache
    assert 3 not in cache

    assert cache.standard_unit_size == 4
    assert cache.total_batch_count == 6  # 3 shards * 2 batches
    assert cache.total_sample_count == 24  # 6 batches * 4 samples
    assert cache.eligible_work_unit_count == 6


def test_dataset_cache_from_sequence(multi_shard_data):
    artifacts, cached_shards = multi_shard_data
    shards_seq = list(cached_shards.values())
    cache = DatasetCache(
        dataset_build_id=artifacts.dataset_build_id,
        dataset_manifest_hash=artifacts.dataset_manifest_hash,
        shards=shards_seq,
    )
    assert cache.shard_count == 3
    assert cache.get_shard(0) == cached_shards[0]
    assert cache[1] == cached_shards[1]


def test_dataset_cache_validation_errors(multi_shard_data):
    artifacts, cached_shards = multi_shard_data

    # Empty build_id
    with pytest.raises(ValueError, match="dataset_build_id"):
        DatasetCache("", artifacts.dataset_manifest_hash, cached_shards)

    # Invalid manifest hash
    with pytest.raises(ValueError, match="dataset_manifest_hash"):
        DatasetCache(artifacts.dataset_build_id, "short_hash", cached_shards)

    # Empty shards
    with pytest.raises(ValueError, match="at least one"):
        DatasetCache(artifacts.dataset_build_id, artifacts.dataset_manifest_hash, {})

    # Invalid type for shards
    with pytest.raises(TypeError, match=r"Mapping.*or Sequence"):
        DatasetCache(artifacts.dataset_build_id, artifacts.dataset_manifest_hash, 123)  # type: ignore[arg-type]

    # Non-CachedShard element
    with pytest.raises(TypeError, match="Expected CachedShard"):
        DatasetCache(
            artifacts.dataset_build_id,
            artifacts.dataset_manifest_hash,
            {0: "not_a_shard"},  # type: ignore[dict-item]
        )

    # Build ID mismatch
    wrong_key = ShardCacheKey("different-build-id", artifacts.dataset_manifest_hash, 0)
    bogus_shard = CachedShard(
        key=wrong_key,
        directory=cached_shards[0].directory,
        root_manifest=cached_shards[0].root_manifest,
        shard_manifest=cached_shards[0].shard_manifest,
    )
    with pytest.raises(ValueError, match="build_id"):
        DatasetCache(artifacts.dataset_build_id, artifacts.dataset_manifest_hash, {0: bogus_shard})


def test_load_work_unit_success(multi_shard_data):
    artifacts, cached_shards = multi_shard_data
    cache = DatasetCache(
        dataset_build_id=artifacts.dataset_build_id,
        dataset_manifest_hash=artifacts.dataset_manifest_hash,
        shards=cached_shards,
    )

    unit_s0_b0 = WorkUnitRef(shard_id=0, batch_id=0, sample_count=4)
    x0, y0, ids0 = cache.load_work_unit(unit_s0_b0)
    assert x0.shape == (4, 3, 2, 2)
    assert y0.shape == (4,)
    assert ids0.shape == (4,)
    assert x0.dtype == np.float32

    unit_s2_b1 = WorkUnitRef(shard_id=2, batch_id=1, sample_count=4)
    x2, y2, ids2 = cache.load_work_unit(unit_s2_b1)
    assert x2.shape == (4, 3, 2, 2)
    assert y2.shape == (4,)
    assert ids2.shape == (4,)

    # Samples across shards should be distinct
    assert len(set(ids0).intersection(set(ids2))) == 0


def test_load_work_unit_failures(multi_shard_data):
    artifacts, cached_shards = multi_shard_data
    cache = DatasetCache(
        dataset_build_id=artifacts.dataset_build_id,
        dataset_manifest_hash=artifacts.dataset_manifest_hash,
        shards=cached_shards,
    )

    # Shard not in cache
    with pytest.raises(KeyError, match="Shard 99 is not present"):
        cache.load_work_unit(WorkUnitRef(shard_id=99, batch_id=0, sample_count=4))

    # Invalid batch_id in existing shard
    with pytest.raises(ValueError, match="Assigned physical batch is missing"):
        cache.load_work_unit(WorkUnitRef(shard_id=0, batch_id=99, sample_count=4))

    # Sample count mismatch
    with pytest.raises(ValueError, match="sample_count mismatch"):
        cache.load_work_unit(WorkUnitRef(shard_id=0, batch_id=0, sample_count=8))

    # Non-WorkUnitRef object
    with pytest.raises(TypeError, match="Expected WorkUnitRef"):
        cache.load_work_unit({"shard_id": 0, "batch_id": 0})  # type: ignore[arg-type]


def test_get_eligible_work_units(multi_shard_data):
    artifacts, cached_shards = multi_shard_data
    cache = DatasetCache(
        dataset_build_id=artifacts.dataset_build_id,
        dataset_manifest_hash=artifacts.dataset_manifest_hash,
        shards=cached_shards,
    )

    units = cache.get_eligible_work_units()
    assert len(units) == 6
    assert units[0] == WorkUnitRef(shard_id=0, batch_id=0, sample_count=4)
    assert units[1] == WorkUnitRef(shard_id=0, batch_id=1, sample_count=4)
    assert units[2] == WorkUnitRef(shard_id=1, batch_id=0, sample_count=4)
    assert units[3] == WorkUnitRef(shard_id=1, batch_id=1, sample_count=4)
    assert units[4] == WorkUnitRef(shard_id=2, batch_id=0, sample_count=4)
    assert units[5] == WorkUnitRef(shard_id=2, batch_id=1, sample_count=4)


def test_verify_all_success_and_failures(multi_shard_data):
    artifacts, cached_shards = multi_shard_data
    cache = DatasetCache(
        dataset_build_id=artifacts.dataset_build_id,
        dataset_manifest_hash=artifacts.dataset_manifest_hash,
        shards=cached_shards,
    )
    # Pristine cache verification must succeed without error
    cache.verify_all()

    # Missing shard referenced in root manifest
    partial_shards = {0: cached_shards[0], 1: cached_shards[1]}
    partial_cache = DatasetCache(
        dataset_build_id=artifacts.dataset_build_id,
        dataset_manifest_hash=artifacts.dataset_manifest_hash,
        shards=partial_shards,
        root_manifest=artifacts.root_manifest_dict,
    )
    with pytest.raises(ValueError, match="missing expected shards"):
        partial_cache.verify_all()
