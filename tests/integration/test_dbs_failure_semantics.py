"""Negative and failure semantics tests for DBS (T7.2).

Follows canonical specifications (docs/DBS_DESIGN.md §13, docs/DBS_IMPLEMENTATION_PLAN.md.md §17):
1. Worker disconnect / failure -> Attempt transitions to FAILED immediately.
2. Invalid or missing DBS stats at epoch boundary -> raises ValueError.
3. Contribution with mismatched batch_ordinal / sample_count / shard_id -> rejected.
4. Invalid contract configuration (equal with K < N, dbs with K <= N, M < K) -> rejected.
5. Cache miss or corrupt batch after RUNNING -> worker/training error, attempt fails.
"""

from unittest.mock import MagicMock

import numpy as np
import pytest

from pbl4.common.work_unit import WorkUnitRef
from pbl4.runtime.batch_scheduler import BatchScheduler, RecoveryCursor
from pbl4.runtime.canonical_model import CanonicalModel, ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointManager
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.coordinator import Coordinator
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.process import _AttemptRunner
from pbl4.runtime.snapshot import CheckpointSnapshot
from pbl4.runtime.synchronization.base import AdmissionCode
from pbl4.runtime.synchronization.context import Member, StrategyContext
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.update_engine import UpdateEngine
from pbl4.runtime.worker_registry import SessionState, WorkerRegistry
from pbl4.runtime.workload_policy import DbsWorkloadPolicy, EqualWorkloadPolicy
from pbl4.runtime.workload_scheduler import WorkloadScheduler
from pbl4.worker.dataset_cache import DatasetCache
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.training_loop import StepAssignment, TrainingLoop
from tests.fixtures.synthetic_dataset import create_synthetic_dataset_artifacts
from tests.test_checkpoint_mechanics import TestOnlySerializer


def _setup_coordinator(tmp_path, policy: str = "dbs", k: int = 4):
    expected_workers = 2
    worker_ids = [0, 1]
    ctx = StrategyContext(
        job_id="job-fail",
        attempt_id="att-fail",
        contract_hash="hash-contract",
        training_strategy="strict_bsp",
        expected_workers=expected_workers,
        update_policy="plain_sgd",
        dataset_build_id="build-fail",
        dataset_manifest_hash="hash-dataset",
        parameter_manifest_hash="hash-param",
        protocol_version=1,
        total_numel=2,
        membership=tuple(Member(w, w + 10) for w in worker_ids),
    )

    registry = WorkerRegistry("att-fail", expected_workers)
    for w in worker_ids:
        registry.register(w + 10, 0, w)

    work_units = [
        WorkUnitRef(shard_id=0, batch_id=0, sample_count=32),
        WorkUnitRef(shard_id=0, batch_id=1, sample_count=32),
        WorkUnitRef(shard_id=1, batch_id=0, sample_count=32),
        WorkUnitRef(shard_id=1, batch_id=1, sample_count=32),
    ]

    batch_scheduler = BatchScheduler(
        work_units=work_units,
        training_seed=42,
        epochs=2,
        work_units_per_step=k,
        worker_ids=worker_ids,
    )
    workload_scheduler = WorkloadScheduler(
        policy=policy,
        worker_ids=worker_ids,
        work_units_per_step=k,
    )

    initial_params = np.array([1.0, 2.0], dtype=np.float32)
    model = CanonicalModel(initial_params, 0, "hash-param")
    engine = UpdateEngine(model, "att-fail", "plain_sgd", 0.1)
    events = EventEmitter("att-fail", "job-fail", capacity=100)

    snapshot_template = CheckpointSnapshot(
        checkpoint_id="tmpl",
        checkpoint_schema_version=1,
        job_id="job-fail",
        created_by_attempt_id="att-fail",
        contract_hash="hash-contract",
        checkpoint_policy="after_each_model_update_blocking",
        checkpoint_policy_version=1,
        training_strategy="strict_bsp",
        dataset_build_id="build-fail",
        dataset_manifest_hash="hash-dataset",
        model_id="test-model",
        model_profile="dense_mlp",
        source_operation_id=0,
        source_step_id=None,
        optimizer="plain_sgd",
        created_at="2026-09-24T00:00:00Z",
        model=ModelSnapshot(0, "hash-param", initial_params.tobytes()),
        recovery_cursor=RecoveryCursor(0, 0),
    )

    coordinator = Coordinator(
        ctx,
        registry,
        create_policy(ctx),
        model,
        engine,
        batch_scheduler,
        CheckpointPolicy("after_each_model_update_blocking"),
        CheckpointManager(tmp_path, TestOnlySerializer()),
        snapshot_template,
        events,
        workload_scheduler=workload_scheduler,
    )

    coordinator.advance_initialization()
    for w in worker_ids:
        registry.transition(w, w + 10, SessionState.REGISTERING, 0)
    coordinator.advance_initialization()
    for w in worker_ids:
        registry.transition(w, w + 10, SessionState.PROVISIONING, 0)
        registry.transition(w, w + 10, SessionState.SHARD_READY, 0)
    coordinator.advance_initialization()
    for w in worker_ids:
        registry.transition(w, w + 10, SessionState.MODEL_SYNCING, 0)
        registry.transition(w, w + 10, SessionState.READY, 0)
    coordinator.advance_initialization()

    return coordinator, workload_scheduler, batch_scheduler, registry


def test_failure_worker_disconnect_fails_attempt_immediately(tmp_path) -> None:
    """Worker failure mid-step causes Attempt to transition to FAILED without redistribution."""
    coordinator, _, _, _ = _setup_coordinator(tmp_path)
    op = coordinator.open_step()
    assert op is not None

    # Worker 0 fails/disconnects
    coordinator.worker_failed(0, 10)

    snap = coordinator.snapshot()
    assert snap["state"] == "FAILED"
    assert snap["step_state"] != "COMMITTED"

    # Step cannot continue or complete
    with pytest.raises(ValueError, match="Attempt/Step progression is blocked"):
        coordinator.open_step()


def test_failure_mismatched_contribution_rejected(tmp_path) -> None:
    """StrictBSP admission rejects contributions with mismatched batch_ordinal or sample_count."""
    coordinator, _, _, _ = _setup_coordinator(tmp_path)
    op = coordinator.open_step()
    grad = np.array([0.1, 0.2], dtype=np.float32)

    # 1. Wrong batch_ordinal (assigned 0, sends 99)
    bad_ordinal = Contribution.from_gradient(
        grad,
        attempt_id="att-fail",
        session_id=10,
        worker_id=0,
        operation_id=op.operation_id,
        step_id=op.step_id,
        model_version=0,
        shard_id=op.assignments[0].shard_id,
        batch_id=op.assignments[0].batch_id,
        batch_ordinal=99,
        sample_count=op.assignments[0].sample_count,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )
    decision1, _ = coordinator.admit(bad_ordinal)
    assert decision1.code == AdmissionCode.REJECT_ASSIGNMENT
    assert decision1.update_plan is None

    # 2. Wrong sample_count (assigned 64, sends 10)
    bad_sample_count = Contribution.from_gradient(
        grad,
        attempt_id="att-fail",
        session_id=10,
        worker_id=0,
        operation_id=op.operation_id,
        step_id=op.step_id,
        model_version=0,
        shard_id=op.assignments[0].shard_id,
        batch_id=op.assignments[0].batch_id,
        batch_ordinal=0,
        sample_count=10,
        parameter_manifest_hash="hash-param",
        tensor_id=1,
        compute_ms=100.0,
    )
    decision2, _ = coordinator.admit(bad_sample_count)
    assert decision2.code == AdmissionCode.REJECT_ASSIGNMENT
    assert decision2.update_plan is None


def test_failure_missing_stats_at_epoch_boundary_fails_fast() -> None:
    """Invalid or missing DBS stats at epoch boundary raises ValueError; no silent fallback."""
    scheduler = WorkloadScheduler(
        policy="dbs",
        worker_ids=[0, 1],
        work_units_per_step=4,
    )
    scheduler.plan_for_epoch(0)

    # Missing stats for worker 1
    grad = np.array([1.0, 2.0], dtype=np.float32)
    c0 = Contribution.from_gradient(
        grad,
        attempt_id="att-fail",
        session_id=10,
        worker_id=0,
        operation_id=0,
        step_id=0,
        model_version=0,
        shard_id=0,
        batch_id=0,
        batch_ordinal=0,
        sample_count=64,
        parameter_manifest_hash="hash",
        tensor_id=1,
        compute_ms=100.0,
    )
    scheduler.record_committed([c0], epoch=0)

    # Epoch 0 completes: must raise ValueError and NOT fallback to Equal
    with pytest.raises(ValueError, match="missing sample stats for workers \\[1\\]"):
        scheduler.on_epoch_completed(0)


def test_failure_contract_validation_rejects_invalid_k_and_m() -> None:
    """Contract and scheduler reject invalid K and M configurations before RUNNING."""
    # 1. Equal policy requires K >= N
    with pytest.raises(ValueError, match=r"total_units .* must be >= worker count"):
        EqualWorkloadPolicy.plan(epoch=0, worker_ids=[0, 1, 2], total_units=2)

    with pytest.raises(ValueError, match="work_units_per_step must be >= worker count"):
        WorkloadScheduler(policy="equal", worker_ids=[0, 1, 2], work_units_per_step=2)

    # 2. DBS policy requires K > N
    with pytest.raises(ValueError, match=r"must be strictly greater than worker count"):
        DbsWorkloadPolicy.plan(
            epoch=1,
            worker_ids=[0, 1, 2],
            total_units=3,
            stats=[],
        )

    with pytest.raises(ValueError, match="work_units_per_step must be > worker count"):
        WorkloadScheduler(policy="dbs", worker_ids=[0, 1, 2], work_units_per_step=3)

    # 3. BatchScheduler requires M >= K
    units = [WorkUnitRef(shard_id=0, batch_id=0, sample_count=32)]
    with pytest.raises(ValueError, match="Not enough work units in catalog"):
        BatchScheduler(
            work_units=units,
            training_seed=42,
            epochs=1,
            work_units_per_step=2,  # M=1 < K=2
            worker_ids=[0],
        )

    # 4. _AttemptRunner contract validation
    session = _AttemptRunner.__new__(_AttemptRunner)
    session._process = MagicMock()
    session._process._manifest.parameter_manifest_hash = "hash-param"
    session._payload = {
        "execution_mode": "FRESH",
        "resolved_contract": {
            "model": {
                "model_id": "resnet18_groupnorm",
                "profile": "RESNET18_GROUPNORM_V1",
                "parameter_manifest_hash": "hash-param",
            },
            "synchronization": {"training_strategy": "strict_bsp", "expected_workers": 2},
            "checkpoint_policy": {
                "type": "after_each_model_update_blocking",
                "schema_version": 1,
            },
            "update_policy": {"type": "plain_sgd"},
            "protocols": {"dtp_version": 1, "mcp_version": 1},
            "workload": {"policy": "unsupported_policy", "work_units_per_step": 4},
        },
    }
    with pytest.raises(ValueError, match="policy must be 'equal' or 'dbs'"):
        session._validate_contract()

    session._payload["resolved_contract"]["workload"] = {
        "policy": "dbs",
        "work_units_per_step": 0,
    }
    with pytest.raises(ValueError, match="must be positive integer"):
        session._validate_contract()


def test_failure_cache_miss_after_running_raises(tmp_path) -> None:
    """Accessing non-existent batch or shard in DatasetCache raises KeyError and halts worker."""
    artifacts = create_synthetic_dataset_artifacts(
        destination_dir=tmp_path / "artifacts",
        dataset_build_id="build-test-fail-cache",
        shard_count=1,
        batches_per_shard=1,
        batch_size=4,
        input_shape=(3, 2, 2),
    )
    shard_cache = ShardCache(tmp_path / "cache")
    key0 = ShardCacheKey(artifacts.dataset_build_id, artifacts.dataset_manifest_hash, shard_id=0)
    cached0 = shard_cache.publish(
        key0,
        artifacts.root_manifest_bytes,
        artifacts.shard_manifest_bytes[0],
        artifacts.shard_batch_bytes[0],
    )
    cache = DatasetCache(
        dataset_build_id=artifacts.dataset_build_id,
        dataset_manifest_hash=artifacts.dataset_manifest_hash,
        shards={0: cached0},
    )

    # Cache only contains shard 0; accessing shard 99 raises KeyError
    with pytest.raises(KeyError, match="Shard 99 is not present in DatasetCache"):
        cache.get_shard(99)

    # Multi-unit computation with missing batch in cache raises ValueError
    mock_adapter = MagicMock()
    loop = TrainingLoop(mock_adapter, cache, model_version=0)
    assignment = StepAssignment(
        attempt_id="att-fail",
        session_id=10,
        worker_id=0,
        operation_id=1,
        step_id=1,
        input_model_version=0,
        batch_ordinal=0,
        work_units=(WorkUnitRef(shard_id=99, batch_id=0, sample_count=32),),
    )

    with pytest.raises(ValueError, match="does not match locally cached shards"):
        loop.compute(assignment)
