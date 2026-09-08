"""Durability mechanics use an explicitly test-only serialization format."""

import json
from dataclasses import asdict, replace

import numpy as np
import pytest

from pbl4.common.hashing import canonical_json_bytes, sha256_bytes
from pbl4.runtime.batch_scheduler import RecoveryCursor
from pbl4.runtime.canonical_model import ModelSnapshot
from pbl4.runtime.checkpoint import CheckpointManager, CheckpointSerializer
from pbl4.runtime.checkpoint_policy import CheckpointPolicy
from pbl4.runtime.event_emitter import EventEmitter
from pbl4.runtime.heartbeat import HeartbeatMonitor
from pbl4.runtime.metrics import MetricsCollector
from pbl4.runtime.snapshot import CheckpointSnapshot
from pbl4.runtime.worker_registry import WorkerRegistry


class TestOnlySerializer(CheckpointSerializer):
    """TEST fixture encoding, deliberately not a production V1 payload format."""

    __test__ = False

    def serialize(self, snapshot):
        payload = b"TEST ONLY:" + snapshot.model._parameters
        fields = asdict(snapshot)
        fields["model"].pop("_parameters")
        fields["model_sha256"] = sha256_bytes(payload)
        body = canonical_json_bytes(fields)
        return payload, canonical_json_bytes(
            {
                "body": fields,
                "metadata_sha256": sha256_bytes(body),
            }
        )

    def deserialize(self, payload, metadata):
        record = json.loads(metadata)
        fields = record["body"]
        if record["metadata_sha256"] != sha256_bytes(canonical_json_bytes(fields)):
            raise ValueError("Test metadata integrity failure")
        if fields.pop("model_sha256") != sha256_bytes(payload) or not payload.startswith(
            b"TEST ONLY:"
        ):
            raise ValueError("Test payload integrity failure")
        model = fields.pop("model")
        cursor = fields.pop("recovery_cursor")
        return CheckpointSnapshot(
            **fields,
            model=ModelSnapshot(**model, _parameters=payload[len(b"TEST ONLY:") :]),
            recovery_cursor=RecoveryCursor(**cursor),
        )


def snapshot(checkpoint_id="checkpoint"):
    return CheckpointSnapshot(
        checkpoint_id,
        1,
        "job",
        "attempt",
        "contract",
        "after_each_model_update_blocking",
        1,
        "strict_bsp",
        "dataset",
        "dataset-hash",
        "test-model",
        "TEST_ONLY",
        0,
        0,
        "plain_sgd",
        "2026-09-08T00:00:00Z",
        ModelSnapshot(8, "manifest", np.array([8.5, 18.5], dtype=np.float32).tobytes()),
        RecoveryCursor(0, 1),
    )


def test_atomic_roundtrip_and_immutable_complete(tmp_path):
    manager = CheckpointManager(tmp_path, TestOnlySerializer())
    saved = manager.write(snapshot())
    assert saved.state == "COMPLETE"
    assert manager.verify(saved) == snapshot()
    assert manager.write(snapshot()) == saved
    with pytest.raises(ValueError):
        manager.write(replace(snapshot(), recovery_cursor=RecoveryCursor(1, 0)))
    assert manager.verify(saved) == snapshot()
    assert not list(tmp_path.glob(".tmp-*"))


@pytest.mark.parametrize("failure", ["write", "fsync", "rename", "verify"])
def test_failed_new_checkpoint_preserves_previous(tmp_path, monkeypatch, failure):
    manager = CheckpointManager(tmp_path, TestOnlySerializer())
    previous = manager.write(snapshot("previous"))

    def fail(*args, **kwargs):
        raise OSError("injected storage failure")

    with monkeypatch.context() as patch:
        if failure == "write":
            patch.setattr(manager, "_write_file", fail)
        elif failure == "fsync":
            patch.setattr("pbl4.runtime.checkpoint.os.fsync", fail)
        elif failure == "rename":
            patch.setattr("pbl4.runtime.checkpoint.os.rename", fail)
        else:
            patch.setattr(manager, "verify", fail)
        with pytest.raises(OSError):
            manager.write(snapshot("next"))
    assert manager.verify(previous) == snapshot("previous")
    assert not list(tmp_path.glob(".tmp-*"))


def test_size_hash_corruption_and_wrong_root(tmp_path):
    manager = CheckpointManager(tmp_path, TestOnlySerializer())
    complete = manager.write(snapshot())
    payload = complete.directory / "model.bin"
    original = payload.read_bytes()
    payload.write_bytes(b"x" * len(original))
    with pytest.raises(ValueError):
        manager.verify(complete)
    payload.write_bytes(original + b"x")
    with pytest.raises(ValueError):
        manager.verify(complete)
    payload.write_bytes(original)
    with pytest.raises(ValueError):
        manager.verify(replace(complete, directory=tmp_path / ".tmp-foreign"))


def test_restore_requires_new_attempt_and_same_pinned_contract(tmp_path):
    manager = CheckpointManager(tmp_path, TestOnlySerializer())
    complete = manager.write(snapshot())
    expected = replace(snapshot(), created_by_attempt_id="new-attempt")
    restored = manager.restore(complete, expected)
    assert restored.model.model_version == 8
    assert restored.recovery_cursor == RecoveryCursor(0, 1)
    with pytest.raises(ValueError):
        manager.restore(complete, snapshot())
    for field in (
        "job_id",
        "contract_hash",
        "dataset_build_id",
        "dataset_manifest_hash",
        "model_id",
        "model_profile",
        "checkpoint_policy",
    ):
        with pytest.raises(ValueError):
            manager.restore(complete, replace(expected, **{field: "foreign"}))
    with pytest.raises(ValueError):
        manager.restore(complete, replace(expected, checkpoint_schema_version=99))
    with pytest.raises(ValueError):
        manager.restore(
            complete,
            replace(
                expected,
                model=replace(
                    expected.model,
                    parameter_manifest_hash="foreign",
                ),
            ),
        )


def test_policy_requires_both_gates_and_caps_retries():
    policy = CheckpointPolicy()
    assert not policy.requires_checkpoint(update_completed=True, synchronization_complete=False)
    assert policy.requires_checkpoint(update_completed=True, synchronization_complete=True)
    assert not policy.allows_commit(synchronization_complete=True, checkpoint_state="WRITING")
    assert not policy.allows_commit(synchronization_complete=False, checkpoint_state="COMPLETE")
    assert policy.allows_commit(synchronization_complete=True, checkpoint_state="COMPLETE")
    assert [policy.may_retry(n) for n in range(4)] == [True, True, True, False]


def test_events_are_historical_and_overflow_preserves_priority_and_sequence():
    emitter = EventEmitter("attempt", "job", capacity=2)
    details = {"nested": {"value": [1, 2]}}
    event = emitter.emit("model.updated", details, "now")
    details["nested"]["value"][0] = 99
    copy = event.details
    copy["nested"]["value"][1] = 88
    assert event.details == {"nested": {"value": [1, 2]}}
    emitter.emit("metric.sample", {"compute_ms": 1}, "now")
    emitter.emit("checkpoint.saved", {"checkpoint_id": "c"}, "now")
    retained = emitter.drain()
    assert [e.runtime_event_seq for e in retained] == [1, 3]
    assert emitter.snapshot()["dropped_event_count"] == 1
    assert emitter.snapshot()["last_runtime_event_seq"] == 3


def test_management_outage_keeps_producer_bounded():
    emitter = EventEmitter("attempt", "job", capacity=2)
    for _ in range(100):
        emitter.emit("metric.sample", {"compute_ms": 1}, "now")
    assert emitter.snapshot() == {
        "last_runtime_event_seq": 100,
        "dropped_event_count": 98,
        "queued_event_count": 2,
    }
    assert [e.runtime_event_seq for e in emitter.drain(after_sequence=99)] == [100]
    with pytest.raises(TypeError):
        emitter.emit("model.updated", {"parameters": np.ones(2)}, "now")


def test_liveness_progress_and_scalar_metrics():
    registry = WorkerRegistry("attempt", 1)
    registry.register(1, 0)
    monitor = HeartbeatMonitor(registry, timeout_seconds=15)
    assert monitor.expired(14) == ()
    assert len(monitor.expired(15)) == 1
    registry.heartbeat(0, 1, 14)
    assert monitor.expired(15) == ()
    metrics = MetricsCollector()
    metrics.record("compute_ms", 2)
    metrics.record("compute_ms", 4)
    assert metrics.snapshot()["compute_ms"] == {"count": 2, "total": 6, "mean": 3}
    with pytest.raises(ValueError):
        metrics.record("compute_ms", float("nan"))
