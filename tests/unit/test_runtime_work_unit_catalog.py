"""Production Runtime Work Unit catalog invariants."""

from pbl4.runtime.process import _AttemptRunner


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
