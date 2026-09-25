"""Unit tests for StrictBSP admission against multi-WorkUnit BatchAssignment."""

import numpy as np

from pbl4.common.work_unit import WorkUnitRef
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.synchronization.base import AdmissionCode as Code
from pbl4.runtime.synchronization.base import ParameterApplied
from pbl4.runtime.synchronization.context import (
    BatchAssignment,
    Member,
    OperationContext,
    StrategyContext,
)
from pbl4.runtime.synchronization.strict_bsp import StrictBSP


def _strategy_context(n=2) -> StrategyContext:
    return StrategyContext(
        job_id="job-1",
        attempt_id="att-1",
        contract_hash="hash-contract",
        training_strategy="strict_bsp",
        expected_workers=n,
        update_policy="plain_sgd",
        dataset_build_id="build-1",
        dataset_manifest_hash="hash-dataset",
        parameter_manifest_hash="hash-param",
        protocol_version=1,
        total_numel=4,
        membership=tuple(Member(w, w + 10) for w in range(n)),
    )


def test_strict_bsp_multi_unit_admission() -> None:
    ctx = _strategy_context(2)
    policy = StrictBSP(ctx)

    # Worker 0 receives 2 WorkUnits (total samples = 20 + 30 = 50)
    units_w0 = (
        WorkUnitRef(shard_id=0, batch_id=1, sample_count=20),
        WorkUnitRef(shard_id=1, batch_id=2, sample_count=30),
    )
    # Worker 1 receives 1 WorkUnit (total samples = 25)
    units_w1 = (WorkUnitRef(shard_id=1, batch_id=3, sample_count=25),)

    assignments = (
        BatchAssignment(worker_id=0, batch_ordinal=0, work_units=units_w0),
        BatchAssignment(worker_id=1, batch_ordinal=0, work_units=units_w1),
    )
    assert assignments[0].shard_id == 0
    assert assignments[0].batch_id == 1
    assert assignments[0].sample_count == 50

    op = OperationContext(
        operation_id=0,
        step_id=0,
        epoch=0,
        batch_ordinal=0,
        input_model_version=0,
        assignments=assignments,
    )
    policy.open_operation(op)

    grad = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)

    # 1. Worker 0 submits contribution matching multi-unit assignment
    c0 = Contribution.from_gradient(
        grad,
        attempt_id="att-1",
        session_id=10,
        worker_id=0,
        operation_id=0,
        step_id=0,
        model_version=0,
        shard_id=0,
        batch_id=1,
        batch_ordinal=0,
        sample_count=50,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=120.0,
    )
    decision0 = policy.admit(c0)
    assert decision0.code == Code.ACCEPT
    assert decision0.update_plan is None

    # 2. Worker 1 submits matching contribution -> triggers N/N barrier
    c1 = Contribution.from_gradient(
        grad,
        attempt_id="att-1",
        session_id=11,
        worker_id=1,
        operation_id=0,
        step_id=0,
        model_version=0,
        shard_id=1,
        batch_id=3,
        batch_ordinal=0,
        sample_count=25,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=95.0,
    )
    decision1 = policy.admit(c1)
    assert decision1.code == Code.ACCEPT
    assert decision1.update_plan is not None

    plan = decision1.update_plan
    assert plan.total_sample_count == 75
    assert len(plan.contributions) == 2
    assert plan.contributions[0].worker_id == 0
    assert plan.contributions[0].compute_ms == 120.0
    assert plan.contributions[1].worker_id == 1
    assert plan.contributions[1].compute_ms == 95.0

    # 3. Model update applied & Parameter ACK barrier
    policy.mark_update_published(plan, 1)
    ack0 = policy.ack_parameter_applied(
        ParameterApplied("att-1", 10, 0, 0, 0, 1),
    )
    assert ack0.code == Code.ACCEPT
    assert not policy.synchronization_complete

    ack1 = policy.ack_parameter_applied(
        ParameterApplied("att-1", 11, 1, 0, 0, 1),
    )
    assert ack1.code == Code.ACCEPT
    assert policy.synchronization_complete


def test_strict_bsp_rejects_sample_count_mismatch() -> None:
    ctx = _strategy_context(2)
    policy = StrictBSP(ctx)

    units_w0 = (
        WorkUnitRef(shard_id=0, batch_id=1, sample_count=20),
        WorkUnitRef(shard_id=1, batch_id=2, sample_count=30),
    )
    assignments = (
        BatchAssignment(worker_id=0, batch_ordinal=0, work_units=units_w0),
        BatchAssignment(
            worker_id=1,
            batch_ordinal=0,
            work_units=(WorkUnitRef(shard_id=1, batch_id=3, sample_count=25),),
        ),
    )
    op = OperationContext(
        operation_id=0,
        step_id=0,
        epoch=0,
        batch_ordinal=0,
        input_model_version=0,
        assignments=assignments,
    )
    policy.open_operation(op)

    grad = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)

    # Worker 0 submits wrong sample_count (e.g. only 20 instead of 50)
    c_bad_samples = Contribution.from_gradient(
        grad,
        attempt_id="att-1",
        session_id=10,
        worker_id=0,
        operation_id=0,
        step_id=0,
        model_version=0,
        shard_id=0,
        batch_id=1,
        batch_ordinal=0,
        sample_count=20,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
    )
    decision = policy.admit(c_bad_samples)
    assert decision.code == Code.REJECT_ASSIGNMENT


def test_strict_bsp_rejects_batch_ordinal_mismatch() -> None:
    ctx = _strategy_context(2)
    policy = StrictBSP(ctx)

    assignments = (
        BatchAssignment(
            worker_id=0,
            batch_ordinal=0,
            work_units=(WorkUnitRef(shard_id=0, batch_id=1, sample_count=20),),
        ),
        BatchAssignment(
            worker_id=1,
            batch_ordinal=0,
            work_units=(WorkUnitRef(shard_id=1, batch_id=3, sample_count=25),),
        ),
    )
    op = OperationContext(
        operation_id=0,
        step_id=0,
        epoch=0,
        batch_ordinal=0,
        input_model_version=0,
        assignments=assignments,
    )
    policy.open_operation(op)

    grad = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)

    # Worker 0 submits wrong batch_ordinal (1 instead of 0)
    c_bad_ordinal = Contribution.from_gradient(
        grad,
        attempt_id="att-1",
        session_id=10,
        worker_id=0,
        operation_id=0,
        step_id=0,
        model_version=0,
        shard_id=0,
        batch_id=1,
        batch_ordinal=1,
        sample_count=20,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
    )
    decision = policy.admit(c_bad_ordinal)
    assert decision.code == Code.REJECT_ASSIGNMENT
