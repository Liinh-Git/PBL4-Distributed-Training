"""DTP/1 async metadata extends payloads without changing header or ACK direction."""

import copy

import pytest

from pbl4.common.errors import ProtocolError
from pbl4.protocol.messages import ParameterApplied, ParameterMeta, build_control_frame
from pbl4.protocol.session import ConnectionPhase, ConnectionProtocolValidator, PeerRole


def metadata():
    return {
        "transfer_purpose": "model_update",
        "parameter_manifest_hash": "c" * 64,
        "total_numel": 2,
        "total_bytes": 8,
        "chunk_count": 1,
        "tensor_encoding": "fp32_le_v1",
        "attempt_id": "attempt",
        "model_version_out": 7,
        "training_strategy": "async_sgd",
        "epoch": 2,
        "work_units": [{"shard_id": 0, "batch_id": 4, "sample_count": 3}],
        "gradient_result": {"operation_id": 15, "applied": False, "staleness": 7},
    }


def test_async_meta_requires_negotiation_and_allows_idle_dispatch():
    meta = ParameterMeta.from_dict(metadata())
    frame = build_control_frame(meta, session_id=10, worker_id=0, operation_id=16, tensor_id=0)
    validator = ConnectionProtocolValidator(inbound_peer=PeerRole.RUNTIME)
    validator.bind(10, 0)
    validator.set_phase(ConnectionPhase.WAITING_PARAMETER)
    with pytest.raises(ProtocolError, match="negotiated"):
        validator.validate(frame.header, meta)
    validator.asynchronous = True
    validator.set_phase(ConnectionPhase.WAITING_NEXT)
    validator.validate(frame.header, meta)
    assert frame.header.operation_id == 16
    assert len(frame.header.pack()) == 48


@pytest.mark.parametrize(
    "change",
    [
        {"source_step_id": 1},
        {"epoch": True},
        {"training_strategy": "strict_bsp"},
        {"work_units": [{"shard_id": 0, "batch_id": 1, "sample_count": True}]},
        {"gradient_result": {"operation_id": 1, "applied": False, "staleness": -1}},
    ],
)
def test_invalid_async_metadata_rejected(change):
    data = copy.deepcopy(metadata())
    data.update(change)
    with pytest.raises(ProtocolError):
        ParameterMeta.from_dict(data)


def test_ack_remains_a_positive_worker_ack_not_a_gradient_result():
    payload = {
        "attempt_id": "attempt",
        "model_version": 7,
        "parameter_manifest_hash": "c" * 64,
        "apply_ok": True,
        "training_strategy": "async_sgd",
    }
    assert ParameterApplied.from_dict(payload).apply_ok is True
    with pytest.raises(ProtocolError):
        ParameterApplied.from_dict({**payload, "apply_ok": False})
    with pytest.raises(ProtocolError):
        ParameterApplied.from_dict({k: v for k, v in payload.items() if k != "training_strategy"})
