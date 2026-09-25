"""Thread-safe multi-shard cache container for worker dataset access."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from threading import Lock
from types import MappingProxyType

import numpy as np

from pbl4.common.work_unit import WorkUnitRef
from pbl4.worker.shard_cache import CachedShard


class DatasetCache:
    """Thread-safe multi-shard cache container for worker dataset access."""

    def __init__(
        self,
        dataset_build_id: str,
        dataset_manifest_hash: str,
        shards: Mapping[int, CachedShard] | Sequence[CachedShard],
        *,
        root_manifest: dict[str, object] | None = None,
    ) -> None:
        if not isinstance(dataset_build_id, str) or not dataset_build_id:
            raise ValueError("dataset_build_id must be a non-empty string")
        if (
            not isinstance(dataset_manifest_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", dataset_manifest_hash) is None
        ):
            raise ValueError("Invalid dataset_manifest_hash (must be 64-char lowercase hex)")

        if isinstance(shards, Mapping):
            shard_dict = dict(shards)
        elif isinstance(shards, Sequence):
            shard_dict = {s.key.shard_id: s for s in shards}
        else:
            raise TypeError("shards must be a Mapping[int, CachedShard] or Sequence[CachedShard]")

        if not shard_dict:
            raise ValueError("DatasetCache requires at least one CachedShard")

        for shard_id, shard in shard_dict.items():
            if not isinstance(shard_id, int) or shard_id < 0:
                raise ValueError(f"Invalid shard_id: {shard_id}")
            if not isinstance(shard, CachedShard):
                raise TypeError(
                    f"Expected CachedShard for shard {shard_id}, got {type(shard).__name__}"
                )
            if shard.key.shard_id != shard_id:
                raise ValueError(
                    f"Shard key shard_id {shard.key.shard_id} "
                    f"does not match dictionary key {shard_id}"
                )
            if shard.key.dataset_build_id != dataset_build_id:
                raise ValueError(
                    f"Shard {shard_id} build_id {shard.key.dataset_build_id!r} "
                    f"!= {dataset_build_id!r}"
                )
            if shard.key.dataset_manifest_hash != dataset_manifest_hash:
                raise ValueError(
                    f"Shard {shard_id} manifest_hash mismatch with dataset_manifest_hash"
                )

        self._dataset_build_id = dataset_build_id
        self._dataset_manifest_hash = dataset_manifest_hash
        self._shards: dict[int, CachedShard] = dict(sorted(shard_dict.items()))
        self._root_manifest = root_manifest or next(iter(self._shards.values())).root_manifest
        self._lock = Lock()

    @property
    def dataset_build_id(self) -> str:
        return self._dataset_build_id

    @property
    def dataset_manifest_hash(self) -> str:
        return self._dataset_manifest_hash

    @property
    def shard_count(self) -> int:
        return len(self._shards)

    @property
    def root_manifest(self) -> dict[str, object]:
        return self._root_manifest

    @property
    def shards(self) -> Mapping[int, CachedShard]:
        return MappingProxyType(self._shards)

    @property
    def standard_unit_size(self) -> int | None:
        """Standard sample count U for Work Units."""
        if self._root_manifest and "batch_size" in self._root_manifest:
            val = self._root_manifest["batch_size"]
            if isinstance(val, int) and val > 0:
                return val
        for s in self._shards.values():
            batches = s.shard_manifest.get("batches", [])
            if (
                isinstance(batches, list)
                and batches
                and isinstance(batches[0].get("sample_count"), int)
            ):
                return batches[0]["sample_count"]
        return None

    @property
    def total_sample_count(self) -> int:
        return sum(
            int(s.shard_manifest.get("sample_count", 0))  # type: ignore[call-overload]
            for s in self._shards.values()
        )

    @property
    def total_batch_count(self) -> int:
        return sum(len(s.shard_manifest.get("batches", [])) for s in self._shards.values())

    @property
    def eligible_work_unit_count(self) -> int:
        """Count of physical batches having standard unit size U."""
        u = self.standard_unit_size
        if u is None:
            return self.total_batch_count
        count = 0
        for s in self._shards.values():
            batches = s.shard_manifest.get("batches", [])
            if isinstance(batches, list):
                for b in batches:
                    if b.get("sample_count") == u:
                        count += 1
        return count

    def __len__(self) -> int:
        return len(self._shards)

    def __contains__(self, shard_id: int) -> bool:
        return shard_id in self._shards

    def __getitem__(self, shard_id: int) -> CachedShard:
        try:
            return self._shards[shard_id]
        except KeyError as exc:
            raise KeyError(f"Shard {shard_id} is not present in DatasetCache") from exc

    def get_shard(self, shard_id: int) -> CachedShard:
        return self[shard_id]

    def load_work_unit(self, unit: WorkUnitRef) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Load physical batch corresponding to the given WorkUnitRef.

        Returns (x, y, sample_ids).
        Raises:
            KeyError: if unit.shard_id is not in cache.
            ValueError: if batch_id is invalid or loaded sample count != unit.sample_count.
        """
        if not isinstance(unit, WorkUnitRef):
            raise TypeError(f"Expected WorkUnitRef, got {type(unit).__name__}")
        shard = self.get_shard(unit.shard_id)
        x, y, sample_ids = shard.load_batch(unit.batch_id)
        if len(x) != unit.sample_count:
            raise ValueError(
                f"WorkUnitRef sample_count mismatch for shard {unit.shard_id} "
                f"batch {unit.batch_id}: expected {unit.sample_count}, got {len(x)}"
            )
        return x, y, sample_ids

    def get_eligible_work_units(self) -> tuple[WorkUnitRef, ...]:
        """Return all eligible WorkUnitRef instances ordered by (shard_id, batch_id)."""
        u = self.standard_unit_size
        units: list[WorkUnitRef] = []
        for shard_id, shard in self._shards.items():
            batches = shard.shard_manifest.get("batches", [])
            if isinstance(batches, list):
                for b in batches:
                    sample_count = b.get("sample_count")
                    if u is None or sample_count == u:
                        units.append(
                            WorkUnitRef(
                                shard_id=shard_id,
                                batch_id=int(b["batch_id"]),
                                sample_count=int(sample_count),
                            )
                        )
        return tuple(units)

    def verify_all(self) -> None:
        """Verify integrity of all cached shards and ensure sample IDs are globally unique."""
        with self._lock:
            if not self._shards:
                raise ValueError("DatasetCache contains no shards")

            expected_shards = self._root_manifest.get("shards")
            if isinstance(expected_shards, list):
                expected_ids = {s.get("shard_id") for s in expected_shards if isinstance(s, dict)}
                actual_ids = set(self._shards.keys())
                missing = expected_ids - actual_ids
                if missing:
                    raise ValueError(
                        f"DatasetCache is missing expected shards from root manifest: "
                        f"{sorted(missing)}"
                    )

            seen_sample_ids: set[int] = set()
            for shard_id, shard in self._shards.items():
                if shard.key.dataset_build_id != self._dataset_build_id:
                    raise ValueError(f"Shard {shard_id} has wrong build ID")
                if shard.key.dataset_manifest_hash != self._dataset_manifest_hash:
                    raise ValueError(f"Shard {shard_id} has wrong manifest hash")

                batches = shard.shard_manifest.get("batches")
                if not isinstance(batches, list):
                    raise ValueError(f"Shard {shard_id} has invalid batches manifest")

                for entry in batches:
                    _, _, sample_ids = shard.load_batch(entry["batch_id"])
                    ids_set = {int(val) for val in sample_ids}
                    if len(ids_set) != len(sample_ids):
                        raise ValueError(
                            f"Duplicate sample IDs within shard {shard_id} "
                            f"batch {entry['batch_id']}"
                        )
                    if seen_sample_ids.intersection(ids_set):
                        raise ValueError(
                            f"Sample identity collision detected between shard {shard_id} "
                            "and other shards"
                        )
                    seen_sample_ids.update(ids_set)
