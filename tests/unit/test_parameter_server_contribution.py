"""Unit tests for compute_ms ingestion into Contribution and ParameterServer._to_contribution."""

import numpy as np
import pytest

from pbl4.protocol.parameter_manifest import ParameterEntry, ParameterManifest
from pbl4.protocol.transfer import CompletedTensorTransfer, TransferIdentity
from pbl4.runtime.contribution import Contribution
from pbl4.runtime.parameter_server import ParameterServer
from pbl4.runtime.worker_registry import WorkerRegistry


def _sample_manifest() -> ParameterManifest:
    return ParameterManifest.create([ParameterEntry(0, "weight", (4,), "float32", 4, 0, 16)])


def test_contribution_compute_ms_validation() -> None:
    grad = np.array([1.0, 2.0, 3.0, 4.0], dtype=np.float32)

    # Valid positive compute_ms
    c = Contribution.from_gradient(
        grad,
        attempt_id="att-1",
        session_id=1,
        worker_id=0,
        operation_id=1,
        step_id=1,
        model_version=0,
        shard_id=0,
        batch_id=1,
        batch_ordinal=0,
        sample_count=32,
        parameter_manifest_hash="hash1",
        tensor_id=1,
        compute_ms=125.5,
    )
    assert c.compute_ms == 125.5

    # Default compute_ms is 0.0
    c_default = Contribution.from_gradient(
        grad,
        attempt_id="att-1",
        session_id=1,
        worker_id=0,
        operation_id=1,
        step_id=1,
        model_version=0,
        shard_id=0,
        batch_id=1,
        batch_ordinal=0,
        sample_count=32,
        parameter_manifest_hash="hash1",
        tensor_id=1,
    )
    assert c_default.compute_ms == 0.0

    # Negative compute_ms raises ValueError
    with pytest.raises(ValueError, match="compute_ms must be non-negative and finite"):
        Contribution.from_gradient(
            grad,
            attempt_id="att-1",
            session_id=1,
            worker_id=0,
            operation_id=1,
            step_id=1,
            model_version=0,
            shard_id=0,
            batch_id=1,
            batch_ordinal=0,
            sample_count=32,
            parameter_manifest_hash="hash1",
            tensor_id=1,
            compute_ms=-5.0,
        )

    # Non-finite compute_ms raises ValueError
    with pytest.raises(ValueError, match="compute_ms must be non-negative and finite"):
        Contribution.from_gradient(
            grad,
            attempt_id="att-1",
            session_id=1,
            worker_id=0,
            operation_id=1,
            step_id=1,
            model_version=0,
            shard_id=0,
            batch_id=1,
            batch_ordinal=0,
            sample_count=32,
            parameter_manifest_hash="hash1",
            tensor_id=1,
            compute_ms=float("inf"),
        )


def test_parameter_server_to_contribution_with_compute_ms() -> None:
    manifest = _sample_manifest()
    registry = WorkerRegistry("att-1", 1)
    ps = ParameterServer(
        "127.0.0.1",
        0,
        attempt_id="att-1",
        job_id="job-1",
        expected_workers=1,
        manifest=manifest,
        registry=registry,
        gradient_handler=lambda c: None,
        parameter_applied_handler=lambda a: None,
        model_init_handler=lambda t: None,
        disconnect_handler=lambda w, s: None,
    )

    grad = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
    identity = TransferIdentity(
        operation_id=1,
        tensor_id=1,
        session_id=10,
        worker_id=0,
    )
    meta = {
        "attempt_id": "att-1",
        "model_version": 0,
        "shard_id": 0,
        "batch_id": 5,
        "batch_ordinal": 0,
        "sample_count": 32,
        "parameter_manifest_hash": manifest.parameter_manifest_hash,
        "compute_ms": 250.75,
    }
    transfer = CompletedTensorTransfer(
        kind="GRADIENT",
        identity=identity,
        metadata=meta,
        data=grad.tobytes(),
    )

    contribution = ps._to_contribution(transfer)
    assert contribution.attempt_id == "att-1"
    assert contribution.worker_id == 0
    assert contribution.compute_ms == 250.75
    assert np.allclose(contribution.gradient, grad)

    # Legacy transfer without compute_ms defaults to 0.0
    meta_legacy = dict(meta)
    del meta_legacy["compute_ms"]
    transfer_legacy = CompletedTensorTransfer(
        kind="GRADIENT",
        identity=identity,
        metadata=meta_legacy,
        data=grad.tobytes(),
    )
    c_legacy = ps._to_contribution(transfer_legacy)
    assert c_legacy.compute_ms == 0.0
