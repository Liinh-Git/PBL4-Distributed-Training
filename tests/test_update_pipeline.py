"""Canonical update pipeline tests with exact, hand-computed numerical oracles."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import numpy as np
import pytest

from pbl4.runtime.aggregator import GradientAggregator
from pbl4.runtime.canonical_model import CanonicalModel
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.gradient_store import GradientStore
from pbl4.runtime.sgd_updater import SGDUpdater
from pbl4.runtime.synchronization.base import AdmissionCode, AdmissionDecision
from pbl4.runtime.synchronization.context import (
    BatchAssignment,
    Member,
    OperationContext,
    StrategyContext,
)
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.synchronization.update_plan import UpdatePlan
from pbl4.runtime.update_engine import UpdateEngine


def plan():
    contributions = tuple(
        Contribution.from_gradient(
            np.array([value, value], dtype=np.float32),
            attempt_id="attempt",
            session_id=w + 1,
            worker_id=w,
            operation_id=0,
            step_id=0,
            model_version=7,
            shard_id=w,
            batch_id=0,
            batch_ordinal=0,
            sample_count=count,
            parameter_manifest_hash="manifest",
            tensor_id=w,
        )
        for w, (value, count) in enumerate([(1, 1), (3, 2), (5, 1)])
    )
    return UpdatePlan("attempt", "strict_bsp", 0, 0, 7, "plain_sgd", contributions)


def test_weighted_three_contribution_oracle_and_concurrent_exactly_once():
    selected = plan()
    aggregate = GradientAggregator().aggregate(selected)
    np.testing.assert_array_equal(aggregate.gradient, [3, 3])
    model = CanonicalModel(np.array([10, 20], dtype=np.float32), 7, "manifest")
    engine = UpdateEngine(model, "attempt", "plain_sgd", 0.5)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: engine.apply_once(selected, aggregate), range(8)))
    assert all(r is results[0] for r in results)
    assert model.snapshot().model_version == 8
    np.testing.assert_array_equal(model.snapshot().parameters, [8.5, 18.5])
    with pytest.raises(ValueError):
        model.snapshot().parameters.setflags(write=True)
    with pytest.raises(ValueError):
        UpdateEngine(model, "attempt", "plain_sgd", 0.5)


def test_equal_weights_and_arbitrary_collection_size():
    original = plan()
    for n in (1, 2, 3):
        selected = replace(
            original,
            contributions=tuple(replace(c, sample_count=1) for c in original.contributions[:n]),
        )
        np.testing.assert_array_equal(GradientAggregator().aggregate(selected).gradient, [n, n])


def test_three_admitted_contributions_flow_through_store_and_update():
    original = plan()
    policy = create_policy(
        StrategyContext(
            "job",
            "attempt",
            "contract",
            "strict_bsp",
            3,
            "plain_sgd",
            "dataset",
            "dataset-hash",
            "manifest",
            1,
            2,
            tuple(Member(c.worker_id, c.session_id) for c in original.contributions),
        )
    )
    policy.open_operation(
        OperationContext(
            0,
            0,
            0,
            0,
            7,
            tuple(
                BatchAssignment(c.worker_id, c.shard_id, 0, 0, c.sample_count)
                for c in original.contributions
            ),
        )
    )
    store = GradientStore()
    with pytest.raises(ValueError):
        store.record(
            original.contributions[0],
            AdmissionDecision(
                AdmissionCode.REJECT_MEMBERSHIP,
                "rejected",
            ),
        )
    for c in original.contributions:
        decision = policy.admit(c)
        store.record(c, decision)
    assert store.snapshot("attempt", 0) == original.contributions
    selected = decision.update_plan
    assert selected is not None
    model = CanonicalModel(np.array([10, 20], dtype=np.float32), 7, "manifest")
    engine = UpdateEngine(model, "attempt", "plain_sgd", 0.5)
    aggregate = GradientAggregator().aggregate(selected)
    after = engine.apply_once(selected, aggregate)
    assert after.model_version == 8
    np.testing.assert_array_equal(after.parameters, [8.5, 18.5])
    store.discard("attempt", 0)
    assert store.snapshot("attempt", 0) == ()
    # Selection stays valid after temporary storage is evicted.
    assert engine.apply_once(selected, aggregate) is after


def test_manifest_and_size_mismatch():
    original = plan()
    for bad in (
        replace(original.contributions[-1], parameter_manifest_hash="other"),
        replace(original.contributions[-1], _gradient_bytes=np.ones(1, dtype=np.float32).tobytes()),
    ):
        selected = replace(original, contributions=(*original.contributions[:-1], bad))
        with pytest.raises(ValueError):
            GradientAggregator().aggregate(selected)
    with pytest.raises(ValueError):
        replace(original, contributions=())
    with pytest.raises(ValueError):
        replace(original, contributions=(replace(original.contributions[0], sample_count=0),))


def test_bad_update_and_foreign_aggregate_leave_model_unchanged():
    selected = plan()
    aggregate = GradientAggregator().aggregate(selected)
    model = CanonicalModel(np.array([10, 20], dtype=np.float32), 7, "manifest")
    engine = UpdateEngine(model, "attempt", "plain_sgd", float("inf"))
    before = model.snapshot()
    with pytest.raises(ValueError):
        engine.apply_once(selected, aggregate)
    assert model.snapshot() is before
    with pytest.raises(ValueError):
        engine.apply_once(
            selected, replace(aggregate, plan=replace(selected, update_policy="other"))
        )
    assert model.snapshot() is before
    with pytest.raises(PermissionError):
        model._publish(object(), before, replace(before, model_version=8))


def test_sgd_is_pure_and_rejects_bad_shapes_and_overflow():
    parameters = np.array([10, 20], dtype=np.float32)
    gradient = np.array([2, 4], dtype=np.float32)
    np.testing.assert_array_equal(SGDUpdater().update(parameters, gradient, 0.5), [9, 18])
    np.testing.assert_array_equal(parameters, [10, 20])
    for bad in (np.ones(1, dtype=np.float32), np.ones((1, 2), dtype=np.float32), np.ones(2)):
        with pytest.raises(ValueError):
            SGDUpdater().update(parameters, bad, 0.5)
    with pytest.raises(FloatingPointError):
        SGDUpdater().update(parameters, gradient, 1e300)
