"""Real Worker gradients -> weighted Runtime aggregation -> one plain SGD update."""

import numpy as np
import pytest
from torch.nn import functional

from pbl4.adapter.models.factory import build_model
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.common.work_unit import WorkUnitRef
from pbl4.runtime.aggregator import GradientAggregator
from pbl4.runtime.canonical_model import CanonicalModel
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.synchronization.update_plan import UpdatePlan
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.worker.dataset_cache import DatasetCache
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.training_loop import StepAssignment, TrainingLoop
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts


@pytest.mark.parametrize("counts", [(2, 2, 2), (1, 2, 3), (1, 1, 4)])
def test_six_work_units_three_contributions_match_global_batch_sgd(tmp_path, counts):
    data = create_synthetic_dataset_artifacts(
        tmp_path / "data", shard_count=3, batches_per_shard=2, batch_size=2, input_shape=(3, 4, 4)
    )
    cache = ShardCache(tmp_path / "cache")
    shards = {
        s: cache.publish(
            ShardCacheKey(data.dataset_build_id, data.dataset_manifest_hash, s),
            data.root_manifest_bytes,
            data.shard_manifest_bytes[s],
            data.shard_batch_bytes[s],
        )
        for s in range(3)
    }
    dataset = DatasetCache(data.dataset_build_id, data.dataset_manifest_hash, shards)
    units = tuple(WorkUnitRef(s, b, 2) for s in range(3) for b in range(2))

    def adapter():
        return PyTorchAdapter(
            build_model("small_cnn", initialization_seed=7),
            functional.cross_entropy,
            local_gradient_reduction="mean",
        )

    def flat(bundle):
        return np.concatenate([t.reshape(-1) for t in bundle.tensors]).astype(np.float32)

    reference = adapter()
    initial = flat(reference.export_parameters())
    batches = [dataset.load_work_unit(u) for u in units]
    direct = reference.compute_loss_and_gradients(
        np.concatenate([b[0] for b in batches]), np.concatenate([b[1] for b in batches])
    )
    contributions = []
    offset = 0
    for worker_id, count in enumerate(counts):
        local = adapter()
        assigned = units[offset : offset + count]
        offset += count
        computed = TrainingLoop(local, dataset, 0).compute(
            StepAssignment(
                "attempt",
                worker_id + 1,
                worker_id,
                0,
                0,
                0,
                batch_ordinal=0,
                work_units=assigned,
                expected_sample_count=2 * count,
            )
        )
        gradient = computed.local_gradient
        assert gradient.sample_count == 2 * count
        np.testing.assert_array_equal(flat(local.export_parameters()), initial)
        contributions.append(
            Contribution.from_gradient(
                flat(gradient.bundle),
                attempt_id="attempt",
                session_id=worker_id + 1,
                worker_id=worker_id,
                operation_id=0,
                step_id=0,
                model_version=0,
                shard_id=assigned[0].shard_id,
                batch_id=assigned[0].batch_id,
                batch_ordinal=0,
                sample_count=gradient.sample_count,
                parameter_manifest_hash=local.manifest.parameter_manifest_hash,
                tensor_id=0,
            )
        )
    assert offset == 6 and len(contributions) == 3
    plan = UpdatePlan("attempt", "strict_bsp", 0, 0, 0, "plain_sgd", tuple(contributions))
    aggregate = GradientAggregator().aggregate(plan)
    np.testing.assert_allclose(aggregate.gradient, flat(direct.bundle), rtol=2e-5, atol=2e-6)
    engine = UpdateEngine(
        CanonicalModel(initial, 0, reference.manifest.parameter_manifest_hash),
        "attempt",
        "plain_sgd",
        0.01,
    )
    updated = engine.apply_once(plan, aggregate)
    np.testing.assert_allclose(
        updated.parameters, initial - np.float32(0.01) * flat(direct.bundle), rtol=2e-5, atol=2e-6
    )
    assert updated.model_version == 1
    assert engine.apply_once(plan, aggregate).model_version == 1
