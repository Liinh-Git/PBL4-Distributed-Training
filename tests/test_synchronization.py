"""StrictBSP contract tests using complete tensors, without network peers."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from threading import Barrier

import numpy as np
import pytest

from pbl4.common.hashing import canonical_json_bytes, sha256_canonical_json
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.synchronization.base import AdmissionCode as Code
from pbl4.runtime.synchronization.base import ParameterApplied
from pbl4.runtime.synchronization.context import (
    BatchAssignment,
    Member,
    OperationContext,
    StrategyContext,
)
from pbl4.runtime.synchronization.registry import create_policy


def context(n=3):
    return StrategyContext(
        "job",
        "attempt",
        "contract",
        "strict_bsp",
        n,
        "plain_sgd",
        "dataset",
        "dataset-hash",
        "parameter-hash",
        1,
        2,
        tuple(Member(w, w + 1) for w in range(n)),
    )


def operation(n=3, step=0, version=7):
    return OperationContext(
        step,
        step,
        2,
        4,
        version,
        tuple(BatchAssignment(w, w, 5, 4, w + 1) for w in range(n)),
    )


def contribution(w=0, **changes):
    identity = dict(
        attempt_id="attempt",
        session_id=w + 1,
        worker_id=w,
        operation_id=0,
        step_id=0,
        model_version=7,
        shard_id=w,
        batch_id=5,
        batch_ordinal=4,
        sample_count=w + 1,
        parameter_manifest_hash="parameter-hash",
        tensor_id=w + 10,
    )
    identity.update(changes)
    return Contribution.from_gradient(np.array([1, 2], dtype=np.float32), **identity)


def ack(w=0, **changes):
    return replace(ParameterApplied("attempt", w + 1, w, 0, 0, 8), **changes)


def started(n=3):
    policy = create_policy(context(n))
    policy.open_operation(operation(n))
    return policy


def ready(policy, n=3):
    plans = [policy.admit(contribution(w)).update_plan for w in range(n)]
    assert sum(plan is not None for plan in plans) == 1
    return plans[-1]


@pytest.mark.parametrize("n", [2, 3, 4])
def test_full_membership_then_full_application(n):
    policy = started(n)
    assert policy.snapshot()["accepted_workers"] == []
    assert not policy.synchronization_complete
    for w in range(n):
        result = policy.admit(contribution(w))
        assert result.code == Code.ACCEPT
        if w < n - 1:
            assert result.update_plan is None
    plan = result.update_plan
    assert {c.worker_id for c in plan.contributions} == set(range(n))
    assert plan.total_sample_count == sum(range(1, n + 1))
    assert not policy.synchronization_complete
    policy.mark_update_published(plan, 8)
    assert not policy.synchronization_complete
    for w in range(n):
        assert policy.ack_parameter_applied(ack(w)).code == Code.ACCEPT
        assert policy.synchronization_complete == (w == n - 1)
        assert policy.ack_parameter_applied(ack(w)).code == Code.REJECT_DUPLICATE
    # Resume starts Step zero at model version seven; next Step uses version eight.
    policy.open_operation(operation(n, step=1, version=8))
    assert not policy.synchronization_complete


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"attempt_id": "foreign"}, Code.FATAL_STRATEGY_ERROR),
        ({"session_id": 99}, Code.REJECT_MEMBERSHIP),
        ({"session_id": True}, Code.REJECT_MEMBERSHIP),
        ({"worker_id": 99}, Code.REJECT_MEMBERSHIP),
        ({"worker_id": False}, Code.REJECT_MEMBERSHIP),
        ({"operation_id": -1}, Code.REJECT_WRONG_OPERATION),
        ({"operation_id": 1}, Code.REJECT_WRONG_OPERATION),
        ({"step_id": -1}, Code.REJECT_WRONG_OPERATION),
        ({"step_id": 1}, Code.REJECT_WRONG_OPERATION),
        ({"model_version": 6}, Code.REJECT_MODEL_VERSION),
        ({"model_version": 8}, Code.REJECT_MODEL_VERSION),
        ({"shard_id": 1}, Code.REJECT_ASSIGNMENT),
        ({"batch_id": 6}, Code.REJECT_ASSIGNMENT),
        ({"batch_ordinal": 3}, Code.REJECT_ASSIGNMENT),
        ({"sample_count": 0}, Code.REJECT_ASSIGNMENT),
        ({"sample_count": 2}, Code.REJECT_ASSIGNMENT),
        ({"sample_count": True}, Code.REJECT_ASSIGNMENT),
        ({"parameter_manifest_hash": "other"}, Code.FATAL_STRATEGY_ERROR),
        ({"tensor_id": -1}, Code.FATAL_STRATEGY_ERROR),
    ],
)
def test_rejection_never_counts(changes, code):
    policy = started()
    result = policy.admit(contribution(**changes))
    assert result.code == code
    assert result.reason
    assert result.update_plan is None
    assert policy.snapshot()["accepted_workers"] == []
    assert policy.admit(contribution()).code == Code.ACCEPT


def test_duplicate_cannot_replace_or_issue_another_plan():
    policy = started()
    assert policy.admit(contribution()).code == Code.ACCEPT
    assert policy.admit(contribution(tensor_id=100)).code == Code.REJECT_DUPLICATE
    policy.admit(contribution(1))
    plan = policy.admit(contribution(2)).update_plan
    assert plan is not None
    for w in range(3):
        result = policy.admit(contribution(w, tensor_id=200))
        assert result.code == Code.REJECT_DUPLICATE
        assert result.update_plan is None
    assert [c.tensor_id for c in plan.contributions] == [10, 11, 12]


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"attempt_id": "foreign"}, Code.FATAL_STRATEGY_ERROR),
        ({"session_id": 99}, Code.REJECT_MEMBERSHIP),
        ({"worker_id": 99}, Code.REJECT_MEMBERSHIP),
        ({"operation_id": 1}, Code.REJECT_WRONG_OPERATION),
        ({"step_id": 1}, Code.REJECT_WRONG_OPERATION),
        ({"model_version": 7}, Code.REJECT_MODEL_VERSION),
        ({"model_version": 9}, Code.REJECT_MODEL_VERSION),
    ],
)
def test_wrong_ack_cannot_complete(changes, code):
    policy = started()
    plan = ready(policy)
    policy.mark_update_published(plan, 8)
    policy.ack_parameter_applied(ack(1))
    policy.ack_parameter_applied(ack(2))
    assert policy.ack_parameter_applied(ack(**changes)).code == code
    assert not policy.synchronization_complete
    assert policy.ack_parameter_applied(ack()).code == Code.ACCEPT
    assert policy.synchronization_complete


def test_tensor_is_complete_fp32_and_alias_safe():
    values = np.array([1, 2], dtype=np.float32)
    original = contribution()
    identities = {
        key: getattr(original, key)
        for key in original.__dataclass_fields__
        if key != "_gradient_bytes"
    }
    c = Contribution.from_gradient(values, **identities)
    values[:] = 100
    np.testing.assert_array_equal(c.gradient, [1, 2])
    with pytest.raises(ValueError):
        c.gradient[0] = 99
    with pytest.raises(ValueError):
        c.gradient.setflags(write=True)
    for malformed in (
        np.ones(2),
        np.ones((1, 2), dtype=np.float32),
        np.array([], dtype=np.float32),
        np.array([np.nan], dtype=np.float32),
    ):
        with pytest.raises(ValueError):
            Contribution.from_gradient(malformed, **identities)
    with pytest.raises(ValueError):
        replace(c, _gradient_bytes=b"x")
    policy = started()
    assert policy.admit(
        replace(c, _gradient_bytes=np.ones(1, dtype=np.float32).tobytes())
    ).code == (Code.FATAL_STRATEGY_ERROR)


def test_plan_context_and_diagnostics_have_no_mutable_aliases():
    members = list(context().membership)
    ctx = replace(context(), membership=members)
    members.clear()
    assert len(ctx.membership) == 3
    policy = create_policy(ctx)
    assignments = list(operation().assignments)
    op = replace(operation(), assignments=assignments)
    assignments.clear()
    policy.open_operation(op)
    plan = ready(policy)
    with pytest.raises(FrozenInstanceError):
        plan.operation_id = 99
    contributions = list(plan.contributions)
    copied = replace(plan, contributions=contributions)
    contributions.clear()
    assert len(copied.contributions) == 3
    diag = policy.snapshot()
    diag["accepted_workers"] = []
    assert policy.snapshot()["accepted_workers"] == [0, 1, 2]


def test_two_final_contributions_create_one_execution_intent():
    policy = started(4)
    policy.admit(contribution(0))
    policy.admit(contribution(1))
    start = Barrier(2)

    def arrive(w):
        start.wait(timeout=5)
        return policy.admit(contribution(w))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(arrive, [2, 3]))
    assert [r.code for r in results] == [Code.ACCEPT, Code.ACCEPT]
    assert sum(r.update_plan is not None for r in results) == 1
    plan = next(r.update_plan for r in results if r.update_plan is not None)
    assert len(plan.contributions) == 4


def test_duplicate_races_with_freezing():
    policy = started()
    policy.admit(contribution(0))
    policy.admit(contribution(1))
    start = Barrier(2)

    def arrive(w):
        start.wait(timeout=5)
        return policy.admit(contribution(w))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(arrive, [0, 2]))
    assert results[0].code == Code.REJECT_DUPLICATE
    assert results[1].update_plan is not None
    assert results[1].update_plan.total_sample_count == 6


def test_failure_closes_admission_and_reconnect_cannot_replace_member():
    policy = started()
    policy.admit(contribution())
    assert policy.worker_failed(0, 99).code == Code.REJECT_MEMBERSHIP
    assert policy.worker_failed(0, 1).code == Code.FATAL_STRATEGY_ERROR
    assert policy.admit(contribution(session_id=100)).code == Code.REJECT_STRATEGY_STATE
    assert policy.snapshot()["accepted_workers"] == []
    assert not policy.synchronization_complete
    with pytest.raises(ValueError):
        policy.open_operation(operation())


def test_final_ack_races_with_failure():
    policy = started()
    plan = ready(policy)
    policy.mark_update_published(plan, 8)
    policy.ack_parameter_applied(ack(0))
    policy.ack_parameter_applied(ack(1))
    start = Barrier(2)

    def complete():
        start.wait(timeout=5)
        return policy.ack_parameter_applied(ack(2))

    def fail():
        start.wait(timeout=5)
        return policy.worker_failed(2, 3)

    with ThreadPoolExecutor(max_workers=2) as pool:
        final_ack = pool.submit(complete)
        failure = pool.submit(fail)
        assert final_ack.result().code in (Code.ACCEPT, Code.REJECT_STRATEGY_STATE)
        assert failure.result().code == Code.FATAL_STRATEGY_ERROR
    assert not policy.synchronization_complete


def test_closed_and_out_of_order_lifecycle():
    policy = create_policy(context())
    assert policy.admit(contribution()).code == Code.REJECT_STRATEGY_STATE
    assert policy.ack_parameter_applied(ack()).code == Code.REJECT_STRATEGY_STATE
    with pytest.raises(ValueError):
        policy.open_operation(operation(step=1))
    policy.open_operation(operation())
    with pytest.raises(ValueError):
        policy.open_operation(operation(step=1))
    plan = ready(policy)
    with pytest.raises(ValueError):
        policy.mark_update_published(replace(plan), 8)
    with pytest.raises(ValueError):
        policy.mark_update_published(plan, 9)
    policy.mark_update_published(plan, 8)
    for w in range(3):
        policy.ack_parameter_applied(ack(w))
    with pytest.raises(ValueError):
        policy.open_operation(operation(step=2, version=8))
    with pytest.raises(ValueError):
        policy.open_operation(operation(step=1, version=7))
    policy.cleanup()
    assert policy.admit(contribution()).code == Code.REJECT_STRATEGY_STATE
    assert not policy.synchronization_complete


def test_fixed_membership_and_assignment_validation():
    with pytest.raises(ValueError):
        replace(context(), membership=(Member(0, 1),) * 3)
    with pytest.raises(ValueError):
        replace(context(), expected_workers=4)
    with pytest.raises(ValueError):
        replace(context(), membership=(Member(0, 1), Member(1, 1), Member(2, 3)))
    for assignments in (
        operation().assignments[:-1],
        (operation().assignments[0],) * 3,
        (*operation().assignments[:-1], BatchAssignment(9, 9, 5, 4, 3)),
    ):
        with pytest.raises(ValueError):
            create_policy(context()).open_operation(replace(operation(), assignments=assignments))
    policy = create_policy(context())
    with pytest.raises(ValueError):
        policy.open_operation(replace(operation(), operation_id=1))


def test_unknown_strategy_has_no_fallback():
    with pytest.raises(ValueError, match="UNSUPPORTED_TRAINING_STRATEGY"):
        create_policy(replace(context(), training_strategy="unknown"))


def test_canonical_json_is_presentation_independent():
    import json

    assert canonical_json_bytes({"z": 1, "a": "Việt"}) == '{"a":"Việt","z":1}'.encode()
    assert sha256_canonical_json(json.loads(' { "z": 1, "a": "Việt" } ')) == (
        sha256_canonical_json({"a": "Việt", "z": 1})
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_canonical_json_rejects_nonfinite(value):
    with pytest.raises(ValueError):
        canonical_json_bytes({"nested": [value]})
