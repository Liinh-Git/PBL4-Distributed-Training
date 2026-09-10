"""Canonical DTP control schema, manifest and tensor-transfer tests."""

from __future__ import annotations

import contextlib
import hashlib
import struct
import threading
import time
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from pbl4.common.errors import ProtocolError
from pbl4.common.hashing import sha256_bytes
from pbl4.protocol.constants import NO_OPERATION, MessageType
from pbl4.protocol.messages import (
    DatasetAssignment,
    EpochEnd,
    Error,
    GradientEnd,
    GradientMeta,
    Heartbeat,
    Hello,
    HelloAck,
    ModelInit,
    ModelManifest,
    ParameterApplied,
    ParameterMeta,
    Ready,
    ShardError,
    ShardReady,
    StepStart,
    Stop,
    build_frame,
    decode_control_message,
)
from pbl4.protocol.parameter_manifest import ParameterEntry, ParameterManifest
from pbl4.protocol.session import (
    ConnectionPhase,
    ConnectionProtocolValidator,
    PeerRole,
)
from pbl4.protocol.tensor_codec import TensorCodec
from pbl4.protocol.transfer import (
    LogicalTransferSender,
    TensorTransferAssembler,
    TransferIdentity,
    build_tensor_transfer_frames,
)


def manifest() -> ParameterManifest:
    return ParameterManifest.create([ParameterEntry(0, "weight", (3,), "float32", 3, 0, 12)])


def payloads() -> list[tuple[type, dict[str, object]]]:
    item = manifest()
    digest = item.parameter_manifest_hash
    return [
        (
            Hello,
            {
                "node_label": "node",
                "client_instance_id": "client",
                "role": "worker",
                "protocol_version": 1,
                "framework_adapter": "pytorch_model_adapter_v1",
                "supported_tensor_encoding": ["fp32_le_v1"],
                "supported_strategy_capabilities": ["strict_bsp"],
            },
        ),
        (
            HelloAck,
            {
                "attempt_id": "a",
                "job_id": "j",
                "session_id": "7",
                "worker_id": 0,
                "expected_workers": 2,
                "training_strategy": "strict_bsp",
                "heartbeat_interval_ms": 5000,
                "heartbeat_timeout_ms": 15000,
                "tensor_encoding": "fp32_le_v1",
                "max_tensor_chunk_bytes": 1048576,
                "server_protocol_version": 1,
            },
        ),
        (
            DatasetAssignment,
            {
                "dataset_build_id": "d",
                "dataset_manifest_hash": "h",
                "shard_id": 0,
                "artifact_base_url": "http://example",
                "root_manifest_path": "manifest.json",
                "expected_shard_count": 2,
                "profile": "CNN_IMAGE_CLASSIFICATION_V1",
            },
        ),
        (
            ShardReady,
            {
                "dataset_build_id": "d",
                "dataset_manifest_hash": "h",
                "shard_id": 0,
                "shard_manifest_hash": "s",
                "verified_batch_count": 1,
                "verified_sample_count": 2,
                "cache_key": "cache",
                "completed_at": "2026-09-08T00:00:00Z",
            },
        ),
        (
            ShardError,
            {"error_code": "HASH", "stage": "VERIFYING", "retryable": False, "message": "bad hash"},
        ),
        (ModelManifest, item.to_dict()),
        (
            ModelInit,
            {
                "initialization_seed": 1,
                "target_model_version": 0,
                "parameter_manifest_hash": digest,
                "total_bytes": 12,
                "initialization_policy_version": 1,
            },
        ),
        (
            ParameterMeta,
            {
                "attempt_id": "a",
                "transfer_purpose": "model_update",
                "source_step_id": 4,
                "model_version_out": 5,
                "parameter_manifest_hash": digest,
                "total_numel": 3,
                "total_bytes": 12,
                "chunk_count": 2,
                "tensor_encoding": "fp32_le_v1",
            },
        ),
        (
            Ready,
            {
                "model_version": 0,
                "parameter_manifest_hash": digest,
                "dataset_build_id": "d",
                "shard_id": 0,
            },
        ),
        (
            StepStart,
            {
                "attempt_id": "a",
                "epoch": 0,
                "step_id": 4,
                "batch_ordinal": 1,
                "model_version": 4,
                "shard_id": 0,
                "batch_id": 1,
                "expected_sample_count": 8,
                "training_strategy": "strict_bsp",
                "parameter_manifest_hash": digest,
            },
        ),
        (
            GradientMeta,
            {
                "attempt_id": "a",
                "model_version": 4,
                "shard_id": 0,
                "batch_id": 1,
                "batch_ordinal": 1,
                "sample_count": 8,
                "parameter_manifest_hash": digest,
                "tensor_encoding": "fp32_le_v1",
                "total_numel": 3,
                "total_bytes": 12,
                "chunk_count": 2,
            },
        ),
        (GradientEnd, {"total_bytes": 12, "chunk_count": 2, "transfer_complete": True}),
        (
            ParameterApplied,
            {
                "attempt_id": "a",
                "model_version": 5,
                "parameter_manifest_hash": digest,
                "apply_ok": True,
                "source_step_id": 4,
            },
        ),
        (
            Heartbeat,
            {
                "attempt_id": "a",
                "worker_state": "READY",
                "local_model_version": 5,
                "last_completed_operation_id": 4,
                "recovery_cursor": {"epoch": 0},
                "monotonic_timestamp_ms": 1.0,
            },
        ),
        (
            EpochEnd,
            {
                "attempt_id": "a",
                "completed_epoch": 0,
                "next_epoch": 1,
                "training_complete": False,
                "latest_checkpoint_id": None,
            },
        ),
        (
            Stop,
            {
                "reason_code": "ATTEMPT_COMPLETED",
                "reason": "done",
                "attempt_state": "COMPLETED",
                "whether_reconnect_allowed": False,
            },
        ),
        (
            Error,
            {
                "error_code": "BAD",
                "scope": "SESSION",
                "severity": "ERROR",
                "message": "bad",
                "retryable": False,
            },
        ),
    ]


class MessageSchemaTest(unittest.TestCase):
    def test_every_control_message_valid_roundtrip(self) -> None:
        for cls, data in payloads():
            with self.subTest(cls=cls.__name__):
                message = cls.from_dict(data)
                self.assertEqual(
                    decode_control_message(cls.MESSAGE_TYPE, message.to_bytes()), message
                )

    def test_every_control_message_rejects_missing_wrong_and_unknown_fields(self) -> None:
        for cls, data in payloads():
            first = next(iter(data))
            missing = dict(data)
            del missing[first]
            wrong = dict(data)
            wrong[first] = object()
            unknown = dict(data)
            unknown["not_canonical"] = 1
            for bad in (missing, wrong, unknown):
                with (
                    self.subTest(cls=cls.__name__, bad=list(bad)),
                    self.assertRaises(ProtocolError),
                ):
                    cls.from_dict(bad)

    def test_enums_and_nonfinite_json_rejected(self) -> None:
        bad = dict(payloads()[0][1])
        bad["role"] = "server"
        with self.assertRaises(ProtocolError):
            Hello.from_dict(bad)
        bad = dict(payloads()[4][1])
        bad["stage"] = "MATERIALIZING"
        with self.assertRaises(ProtocolError):
            ShardError.from_dict(bad)
        gradient = dict(payloads()[10][1])
        gradient["loss"] = float("nan")
        with self.assertRaises(ProtocolError):
            GradientMeta.from_dict(gradient)
        encoded = b'{"loss":NaN}'
        with self.assertRaises(ProtocolError):
            decode_control_message(int(MessageType.GRADIENT_META), encoded)

    def test_invalid_json_roots_rejected(self) -> None:
        for raw in (b"[]", b"null", b'"text"', b"1"):
            with self.subTest(raw=raw), self.assertRaises(ProtocolError):
                decode_control_message(int(MessageType.HELLO), raw)


class ManifestTest(unittest.TestCase):
    def test_hash_uses_canonical_json_without_self_hash(self) -> None:
        item = manifest()
        canonical = item.canonical_bytes()
        self.assertEqual(item.parameter_manifest_hash, sha256_bytes(canonical))
        self.assertNotIn(b"parameter_manifest_hash", canonical)
        self.assertEqual(ParameterManifest.from_dict(item.to_dict()), item)

    def test_layout_rejections(self) -> None:
        base = ParameterEntry(0, "a", (2,), "float32", 2, 0, 8)
        cases = [
            lambda: ParameterEntry(0, "a", (), "float32", 1, 0, 4),
            lambda: ParameterEntry(0, "a", (2,), "float64", 2, 0, 8),
            lambda: ParameterEntry(0, "a", (2,), "float32", 3, 0, 12),
            lambda: ParameterEntry(0, "a", (2,), "float32", 2, 0, 7),
            lambda: ParameterManifest.create(
                [base, ParameterEntry(0, "b", (1,), "float32", 1, 8, 4)]
            ),
            lambda: ParameterManifest.create(
                [base, ParameterEntry(1, "b", (1,), "float32", 1, 12, 4)]
            ),
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(ProtocolError):
                case()


class TensorCodecTest(unittest.TestCase):
    def test_little_endian_fp32_and_chunks(self) -> None:
        raw = TensorCodec.encode([1.0, -2.5, 3.25], expected_numel=3)
        self.assertEqual(raw, struct.pack("<fff", 1.0, -2.5, 3.25))
        self.assertEqual(TensorCodec.chunk(raw, 8), (raw[:8], raw[8:]))
        self.assertEqual(TensorCodec.decode(raw), (1.0, -2.5, 3.25))
        with patch.object(TensorCodec, "decode", side_effect=AssertionError):
            self.assertEqual(TensorCodec.validate_buffer(raw, manifest()), raw)

    def test_nonfinite_size_and_reassembly_errors(self) -> None:
        for values in ([float("nan")], [float("inf")]):
            with self.assertRaises(ProtocolError):
                TensorCodec.encode(values)
        with self.assertRaises(ProtocolError):
            TensorCodec.decode(b"123")
        with self.assertRaises(ProtocolError):
            TensorCodec.validate_buffer(b"1234", manifest())
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ProtocolError):
                TensorCodec.validate_buffer(struct.pack("<fff", 1.0, value, 3.0), manifest())


class TransferTest(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = manifest()
        self.raw = struct.pack("<fff", 1.0, 2.0, 3.0)
        self.identity = TransferIdentity(7, 0, 4, 0)
        self.meta = GradientMeta.from_dict(payloads()[10][1])
        self.end = GradientEnd.from_dict(
            {
                "total_bytes": 12,
                "chunk_count": 2,
                "transfer_complete": True,
                "gradient_sha256": hashlib.sha256(self.raw).hexdigest(),
            }
        )

    def assembler(self) -> TensorTransferAssembler:
        return TensorTransferAssembler(self.manifest, max_model_bytes=12, max_tensor_chunk_bytes=8)

    def test_gradient_exposed_only_after_end(self) -> None:
        assembler = self.assembler()
        assembler.begin_gradient(self.identity, self.meta)
        self.assertIsNone(assembler.add_chunk(self.identity, 0, self.raw[:8]))
        self.assertIsNone(assembler.add_chunk(self.identity, 1, self.raw[8:]))
        completed = assembler.end_gradient(self.identity, self.end)
        self.assertEqual(completed.data, self.raw)
        self.assertEqual(completed.kind, "gradient")

    def test_parameter_completes_without_end(self) -> None:
        data = dict(payloads()[7][1])
        parameter = ParameterMeta.from_dict(data)
        assembler = self.assembler()
        assembler.begin_parameter(self.identity, parameter)
        self.assertIsNone(assembler.add_chunk(self.identity, 0, self.raw[:8]))
        completed = assembler.add_chunk(self.identity, 1, self.raw[8:])
        self.assertIsNotNone(completed)
        self.assertEqual(completed.kind, "parameter")

    def test_chunk_before_meta_duplicate_wrong_index_and_identity(self) -> None:
        assembler = self.assembler()
        with self.assertRaises(ProtocolError):
            assembler.add_chunk(self.identity, 0, self.raw)
        assembler.begin_gradient(self.identity, self.meta)
        assembler.add_chunk(self.identity, 0, self.raw[:8])
        for identity, index in (
            (self.identity, 0),
            (self.identity, 2),
            (TransferIdentity(8, 0, 4, 0), 1),
            (TransferIdentity(7, 1, 4, 0), 1),
            (TransferIdentity(7, 0, 5, 0), 1),
            (TransferIdentity(7, 0, 4, 1), 1),
        ):
            with self.subTest(identity=identity, index=index), self.assertRaises(ProtocolError):
                assembler.add_chunk(identity, index, self.raw[8:])
            self.assertFalse(assembler.active)
            assembler.begin_gradient(self.identity, self.meta)
            assembler.add_chunk(self.identity, 0, self.raw[:8])

    def test_missing_overflow_manifest_mismatch_and_cleanup(self) -> None:
        assembler = self.assembler()
        assembler.begin_gradient(self.identity, self.meta)
        assembler.add_chunk(self.identity, 0, self.raw[:8])
        with self.assertRaises(ProtocolError):
            assembler.end_gradient(self.identity, self.end)
        self.assertFalse(assembler.active)
        bad = dict(self.meta.to_dict())
        bad["parameter_manifest_hash"] = "0" * 64
        with self.assertRaises(ProtocolError):
            assembler.begin_gradient(self.identity, GradientMeta.from_dict(bad))
        self.assertFalse(assembler.active)
        assembler.begin_gradient(self.identity, self.meta)
        with self.assertRaises(ProtocolError):
            assembler.add_chunk(self.identity, 0, self.raw)
        self.assertFalse(assembler.active)
        assembler.discard()
        assembler.discard()
        self.assertFalse(assembler.active)

    def test_identity_and_kind_metadata_are_type_safe(self) -> None:
        for values in (
            (0, 0, 4, 0),
            (7, 0xFFFFFFFF, 4, 0),
            (7, 0, 4, 0xFFFFFFFF),
        ):
            with self.subTest(values=values), self.assertRaises(ProtocolError):
                TransferIdentity(*values)

    def test_frame_builder_rejects_kind_metadata_mismatch(self) -> None:
        parameter = ParameterMeta.from_dict(payloads()[7][1])
        with self.assertRaises(ProtocolError):
            build_tensor_transfer_frames(
                kind="gradient",
                identity=self.identity,
                metadata=parameter,
                data=self.raw,
                chunk_size=8,
            )
        with self.assertRaises(ProtocolError):
            build_tensor_transfer_frames(
                kind="parameter",
                identity=self.identity,
                metadata=self.meta,
                data=self.raw,
                chunk_size=8,
            )
        with self.assertRaises(ProtocolError):
            build_tensor_transfer_frames(
                kind="gradient",
                identity=TransferIdentity(7, 0, NO_OPERATION, 0),
                metadata=self.meta,
                data=self.raw,
                chunk_size=8,
            )

    def test_frame_builder_parameter_has_no_end(self) -> None:
        meta = ParameterMeta.from_dict(payloads()[7][1])
        frames = build_tensor_transfer_frames(
            kind="parameter",
            identity=self.identity,
            metadata=meta,
            data=self.raw,
            chunk_size=8,
        )
        self.assertEqual([f.header.message_type for f in frames], [0x0012, 0x0013, 0x0013])


class SessionAndAtomicityTest(unittest.TestCase):
    def test_binding_rejects_spoof_and_state_order(self) -> None:
        validator = ConnectionProtocolValidator()
        validator.validate(build_frame(0x0001).header)
        validator.bind(7, 0)
        heartbeat = build_frame(0x0030, b"{}", session_id=7, worker_id=0)
        validator.validate(heartbeat.header)
        spoof = build_frame(0x0030, b"{}", session_id=8, worker_id=0)
        with self.assertRaises(ProtocolError):
            validator.validate(spoof.header)
        gradient = build_frame(
            0x0021,
            b"{}",
            session_id=7,
            worker_id=0,
            operation_id=0,
            tensor_id=0,
        )
        with self.assertRaises(ProtocolError):
            validator.validate(gradient.header)
        validator.set_phase(ConnectionPhase.UPLOADING)
        validator.validate(gradient.header)

    def test_runtime_side_rejects_wrong_message_direction(self) -> None:
        validator = ConnectionProtocolValidator(inbound_peer=PeerRole.WORKER)
        wrong_direction = build_frame(0x0002, b"{}", session_id=7, worker_id=0)
        with self.assertRaises(ProtocolError):
            validator.validate(wrong_direction.header)

    def test_epoch_end_is_server_to_worker_only(self) -> None:
        epoch = build_frame(0x0031, b"{}", session_id=7, worker_id=0)
        runtime_inbound = ConnectionProtocolValidator(
            phase=ConnectionPhase.WAITING_NEXT,
            bound_identity=(7, 0),
            inbound_peer=PeerRole.RUNTIME,
        )
        runtime_inbound.validate(epoch.header)
        worker_inbound = ConnectionProtocolValidator(
            phase=ConnectionPhase.WAITING_NEXT,
            bound_identity=(7, 0),
            inbound_peer=PeerRole.WORKER,
        )
        with self.assertRaises(ProtocolError):
            worker_inbound.validate(epoch.header)

    def test_model_init_is_worker_zero_initialization_only(self) -> None:
        valid = build_frame(0x0011, b"{}", session_id=7, worker_id=0)
        validator = ConnectionProtocolValidator(
            phase=ConnectionPhase.INITIALIZING,
            bound_identity=(7, 0),
            inbound_peer=PeerRole.WORKER,
        )
        validator.validate(valid.header)
        for peer, worker, operation, phase in (
            (PeerRole.RUNTIME, 0, NO_OPERATION, ConnectionPhase.INITIALIZING),
            (PeerRole.WORKER, 1, NO_OPERATION, ConnectionPhase.INITIALIZING),
            (PeerRole.WORKER, 0, 4, ConnectionPhase.INITIALIZING),
            (PeerRole.WORKER, 0, NO_OPERATION, ConnectionPhase.READY),
        ):
            candidate = ConnectionProtocolValidator(
                phase=phase,
                bound_identity=(7, worker),
                inbound_peer=peer,
            )
            with (
                self.subTest(peer=peer, worker=worker, phase=phase),
                self.assertRaises(ProtocolError),
            ):
                frame = build_frame(
                    0x0011,
                    b"{}",
                    session_id=7,
                    worker_id=worker,
                    operation_id=operation,
                )
                candidate.validate(frame.header)

    def test_parameter_direction_and_chunks_inherit_meta_context(self) -> None:
        initial_data = dict(payloads()[7][1])
        initial_data.pop("attempt_id")
        initial_data.pop("source_step_id")
        initial_data.pop("model_version_out")
        initial_data.update(transfer_purpose="model_init", model_version=0)
        initial_meta = ParameterMeta.from_dict(initial_data)
        initial = ConnectionProtocolValidator(
            phase=ConnectionPhase.INITIALIZING,
            bound_identity=(7, 0),
            inbound_peer=PeerRole.WORKER,
        )
        meta_frame = build_frame(
            0x0012,
            b"{}",
            session_id=7,
            worker_id=0,
            tensor_id=0,
        )
        initial.validate(meta_frame.header, initial_meta)
        initial.validate(
            build_frame(
                0x0013,
                b"x",
                session_id=7,
                worker_id=0,
                tensor_id=0,
                chunk_index=0,
            ).header
        )
        with self.assertRaises(ProtocolError):
            initial.validate(
                build_frame(
                    0x0013,
                    b"x",
                    session_id=7,
                    worker_id=0,
                    tensor_id=1,
                    chunk_index=1,
                ).header
            )

        for peer, worker, operation in (
            (PeerRole.WORKER, 1, NO_OPERATION),
            (PeerRole.RUNTIME, 0, NO_OPERATION),
            (PeerRole.WORKER, 0, 4),
        ):
            candidate = ConnectionProtocolValidator(
                phase=ConnectionPhase.INITIALIZING,
                bound_identity=(7, worker),
                inbound_peer=peer,
            )
            header = build_frame(
                0x0012,
                b"{}",
                session_id=7,
                worker_id=worker,
                operation_id=operation,
                tensor_id=0,
            ).header
            with (
                self.subTest(peer=peer, worker=worker, operation=operation),
                self.assertRaises(ProtocolError),
            ):
                candidate.validate(header, initial_meta)

        update = ConnectionProtocolValidator(
            phase=ConnectionPhase.WAITING_PARAMETER,
            bound_identity=(7, 0),
            inbound_peer=PeerRole.RUNTIME,
        )
        update.validate(
            build_frame(
                0x0012,
                b"{}",
                session_id=7,
                worker_id=0,
                operation_id=4,
                tensor_id=0,
            ).header,
            ParameterMeta.from_dict(payloads()[7][1]),
        )
        with self.assertRaises(ProtocolError):
            wrong_direction = ConnectionProtocolValidator(
                phase=ConnectionPhase.WAITING_PARAMETER,
                bound_identity=(7, 0),
                inbound_peer=PeerRole.WORKER,
            )
            wrong_direction.validate(
                build_frame(
                    0x0012,
                    b"{}",
                    session_id=7,
                    worker_id=0,
                    operation_id=4,
                    tensor_id=0,
                ).header,
                ParameterMeta.from_dict(payloads()[7][1]),
            )
        with self.assertRaises(ProtocolError):
            wrong_direction.validate(
                build_frame(
                    0x0013,
                    b"x",
                    session_id=7,
                    worker_id=0,
                    operation_id=4,
                    tensor_id=0,
                    chunk_index=0,
                ).header
            )

    def test_pre_registration_error_is_runtime_only_and_unbound(self) -> None:
        error = build_frame(0x00FF, b"{}")
        ConnectionProtocolValidator(inbound_peer=PeerRole.RUNTIME).validate(error.header)
        with self.assertRaises(ProtocolError):
            ConnectionProtocolValidator(inbound_peer=PeerRole.WORKER).validate(error.header)

    def test_transfer_lock_prevents_heartbeat_interleaving(self) -> None:
        order: list[int] = []
        first_chunk_seen = threading.Event()

        def send(_sock: object, frame: object) -> None:
            order.append(frame.header.message_type)
            if frame.header.message_type == 0x0013 and not first_chunk_seen.is_set():
                first_chunk_seen.set()
                time.sleep(0.03)

        sender = LogicalTransferSender(send)
        identity = TransferIdentity(7, 0, 4, 0)
        meta = ParameterMeta.from_dict(payloads()[7][1])
        raw = struct.pack("<fff", 1.0, 2.0, 3.0)
        frames = build_tensor_transfer_frames(
            kind="parameter", identity=identity, metadata=meta, data=raw, chunk_size=8
        )
        heartbeat = build_frame(0x0030, b"{}", session_id=7, worker_id=0)
        transfer_thread = threading.Thread(target=sender.send_transfer, args=(None, frames))
        control_thread = threading.Thread(
            target=lambda: (first_chunk_seen.wait(), sender.send_frame(None, heartbeat))
        )
        transfer_thread.start()
        control_thread.start()
        transfer_thread.join()
        control_thread.join()
        self.assertEqual(order, [0x0012, 0x0013, 0x0013, 0x0030])


class RuntimeSeamTest(unittest.TestCase):
    """Prove wire completion is separate from owner-supplied Runtime policy."""

    def setUp(self) -> None:
        self.manifest = manifest()
        self.raw = struct.pack("<fff", 1.0, 2.0, 3.0)
        self.meta = GradientMeta.from_dict(payloads()[10][1])
        self.end = GradientEnd.from_dict(
            {"total_bytes": 12, "chunk_count": 2, "transfer_complete": True}
        )

    def complete(self, operation_id: int = 4):
        identity = TransferIdentity(7, 0, operation_id, 0)
        assembler = TensorTransferAssembler(
            self.manifest, max_model_bytes=12, max_tensor_chunk_bytes=8
        )
        assembler.begin_gradient(identity, self.meta)
        assembler.add_chunk(identity, 0, self.raw[:8])
        assembler.add_chunk(identity, 1, self.raw[8:])
        return assembler.end_gradient(identity, self.end)

    def test_meta_never_admits_and_complete_transfer_admits_exactly_once(self) -> None:
        admissions: list[object] = []
        assembler = TensorTransferAssembler(
            self.manifest, max_model_bytes=12, max_tensor_chunk_bytes=8
        )
        identity = TransferIdentity(7, 0, 4, 0)
        assembler.begin_gradient(identity, self.meta)
        self.assertEqual(admissions, [])
        assembler.add_chunk(identity, 0, self.raw[:8])
        assembler.add_chunk(identity, 1, self.raw[8:])
        admissions.append(assembler.end_gradient(identity, self.end))
        self.assertEqual(len(admissions), 1)

    def test_duplicate_stale_and_future_are_delegated_to_policy(self) -> None:
        class FakePolicy:
            def __init__(self) -> None:
                self.seen: list[int] = []

            def admit(self, completed: object) -> str:
                operation_id = completed.identity.operation_id
                duplicate = operation_id in self.seen
                self.seen.append(operation_id)
                if duplicate:
                    return "duplicate"
                return "stale" if operation_id < 4 else "future" if operation_id > 4 else "current"

        policy = FakePolicy()
        current = self.complete(4)
        self.assertEqual(policy.admit(current), "current")
        self.assertEqual(policy.admit(current), "duplicate")
        self.assertEqual(policy.admit(self.complete(3)), "stale")
        self.assertEqual(policy.admit(self.complete(5)), "future")

    def test_send_success_is_not_parameter_applied(self) -> None:
        acknowledgements: list[object] = []
        sender = LogicalTransferSender(lambda _sock, _frame: None)
        parameter = ParameterMeta.from_dict(payloads()[7][1])
        frames = build_tensor_transfer_frames(
            kind="parameter",
            identity=TransferIdentity(7, 0, 4, 0),
            metadata=parameter,
            data=self.raw,
            chunk_size=8,
        )
        self.assertIsNone(sender.send_transfer(None, frames))
        self.assertEqual(acknowledgements, [])

    def test_parameter_applied_and_disconnect_preserve_bound_identity(self) -> None:
        @dataclass(frozen=True)
        class SemanticParameterApplied:
            attempt_id: str
            session_id: int
            worker_id: int
            operation_id: int
            model_version: int

        wire = ParameterApplied.from_dict(payloads()[12][1])
        mapped = SemanticParameterApplied(
            attempt_id=wire.attempt_id,
            session_id=7,
            worker_id=0,
            operation_id=4,
            model_version=wire.model_version,
        )
        self.assertEqual(mapped, SemanticParameterApplied("a", 7, 0, 4, 5))

        validator = ConnectionProtocolValidator()
        validator.bind(7, 0)
        self.assertEqual(validator.close(), (7, 0))
        self.assertEqual(validator.phase, ConnectionPhase.CLOSED)

    def test_last_seen_updated_on_heartbeat_and_any_valid_dtp_message(self) -> None:
        import socket

        from pbl4.protocol.messages import build_control_frame
        from pbl4.runtime.heartbeat import HeartbeatMonitor
        from pbl4.runtime.parameter_server import ParameterServer, _Connection
        from pbl4.runtime.worker_registry import SessionState, WorkerRegistry

        registry = WorkerRegistry("attempt-liveness", 1)
        server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id="attempt-liveness",
            job_id="job-liveness",
            expected_workers=1,
            manifest=manifest(),
            registry=registry,
        )
        registry.register(10, time.monotonic(), 0)
        registry.transition(0, 10, SessionState.REGISTERING, time.monotonic())
        registry.transition(0, 10, SessionState.PROVISIONING, time.monotonic())

        validator = ConnectionProtocolValidator(inbound_peer=PeerRole.WORKER)
        validator.bind(10, 0)

        server_sock, client_sock = socket.socketpair()
        try:
            initial_time = time.monotonic() - 10.0
            conn = _Connection(
                sock=server_sock,
                session_id=10,
                worker_id=0,
                validator=validator,
                assembler=TensorTransferAssembler(
                    manifest(), max_model_bytes=12, max_tensor_chunk_bytes=8
                ),
                sender=LogicalTransferSender(lambda s, f: None),
                last_seen=initial_time,
            )
            server._connections[0] = conn

            # Test server query method
            self.assertEqual(server.last_seen(0), initial_time)
            with self.assertRaises(ValueError):
                server.last_seen(99)

            # Start _read_bound in a background daemon thread with clean suppression
            def run_reader() -> None:
                with contextlib.suppress(Exception):
                    server._read_bound(conn)

            read_thread = threading.Thread(target=run_reader, daemon=True)
            read_thread.start()

            # Send SHARD_READY frame -> triggers _read_bound -> updates last_seen & heartbeat
            ready_msg = ShardReady.from_dict(payloads()[3][1])
            frame1 = build_control_frame(ready_msg, session_id=10, worker_id=0)
            frame1.write_to(client_sock, lambda s, b: s.sendall(b))

            # Wait briefly for server thread to process frame
            deadline = time.monotonic() + 2.0
            while server.last_seen(0) == initial_time and time.monotonic() < deadline:
                time.sleep(0.01)

            t1 = server.last_seen(0)
            self.assertGreater(t1, initial_time)
            self.assertEqual(registry.snapshot()[0].state, SessionState.SHARD_READY)
            self.assertEqual(registry.snapshot()[0].last_heartbeat_at, t1)

            # Send HEARTBEAT frame -> triggers _read_bound -> updates last_seen & registry.heartbeat
            time.sleep(0.02)
            hb = Heartbeat.from_dict(
                {
                    "attempt_id": "attempt-liveness",
                    "worker_state": "SHARD_READY",
                    "local_model_version": 0,
                    "last_completed_operation_id": None,
                    "recovery_cursor": {"epoch": 0},
                    "monotonic_timestamp_ms": 200.0,
                }
            )
            frame2 = build_control_frame(hb, session_id=10, worker_id=0)
            frame2.write_to(client_sock, lambda s, b: s.sendall(b))

            deadline = time.monotonic() + 2.0
            while server.last_seen(0) == t1 and time.monotonic() < deadline:
                time.sleep(0.01)

            t2 = server.last_seen(0)
            self.assertGreater(t2, t1)
            self.assertEqual(registry.snapshot()[0].last_heartbeat_at, t2)

            # Verify HeartbeatMonitor does not expire active session
            monitor = HeartbeatMonitor(registry, timeout_seconds=15.0)
            self.assertEqual(monitor.expired(t2 + 5.0), ())
        finally:
            server_sock.close()
            client_sock.close()

    def test_runtime_handles_message_scope_error_without_disconnecting(self) -> None:
        import socket

        from pbl4.protocol.messages import build_control_frame
        from pbl4.runtime.parameter_server import ParameterServer, _Connection
        from pbl4.runtime.worker_registry import SessionState, WorkerRegistry

        received_errors: list[Error] = []
        registry = WorkerRegistry("attempt-err-msg", 1)
        server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id="attempt-err-msg",
            job_id="job-err-msg",
            expected_workers=1,
            manifest=manifest(),
            registry=registry,
            error_handler=lambda w, s, err: received_errors.append(err),
        )
        registry.register(20, time.monotonic(), 0)
        registry.transition(0, 20, SessionState.REGISTERING, time.monotonic())
        registry.transition(0, 20, SessionState.PROVISIONING, time.monotonic())
        registry.transition(0, 20, SessionState.SHARD_READY, time.monotonic())

        validator = ConnectionProtocolValidator(inbound_peer=PeerRole.WORKER)
        validator.bind(20, 0)
        validator.set_phase(ConnectionPhase.SHARD_READY)

        server_sock, client_sock = socket.socketpair()
        try:
            initial_time = time.monotonic() - 5.0
            conn = _Connection(
                sock=server_sock,
                session_id=20,
                worker_id=0,
                validator=validator,
                assembler=TensorTransferAssembler(
                    manifest(), max_model_bytes=12, max_tensor_chunk_bytes=8
                ),
                sender=LogicalTransferSender(lambda s, f: None),
                last_seen=initial_time,
            )
            server._connections[0] = conn

            def run_reader() -> None:
                with contextlib.suppress(Exception):
                    server._read_bound(conn)

            read_thread = threading.Thread(target=run_reader, daemon=True)
            read_thread.start()

            # Send non-fatal MESSAGE scope ERROR
            warn_err = Error.from_dict(
                {
                    "error_code": "FRAME_IGNORED",
                    "scope": "MESSAGE",
                    "severity": "WARNING",
                    "message": "Ignored duplicate chunk",
                    "retryable": True,
                }
            )
            frame = build_control_frame(warn_err, session_id=20, worker_id=0)
            frame.write_to(client_sock, lambda s, b: s.sendall(b))

            deadline = time.monotonic() + 2.0
            while not received_errors and time.monotonic() < deadline:
                time.sleep(0.01)

            self.assertEqual(len(received_errors), 1)
            self.assertEqual(received_errors[0].error_code, "FRAME_IGNORED")
            # Session should NOT be failed, connection still alive
            self.assertEqual(registry.snapshot()[0].state, SessionState.SHARD_READY)
            self.assertEqual(conn.validator.phase, ConnectionPhase.SHARD_READY)
            self.assertIn(0, server._connections)
            self.assertGreater(server.last_seen(0), initial_time)
        finally:
            server_sock.close()
            client_sock.close()

    def test_runtime_handles_session_and_attempt_scope_fatal_errors(self) -> None:
        import socket

        from pbl4.protocol.messages import build_control_frame
        from pbl4.runtime.parameter_server import ParameterServer, _Connection
        from pbl4.runtime.worker_registry import SessionState, WorkerRegistry

        received_errors: list[Error] = []
        registry = WorkerRegistry("attempt-err-fatal", 1)
        server = ParameterServer(
            "127.0.0.1",
            0,
            attempt_id="attempt-err-fatal",
            job_id="job-err-fatal",
            expected_workers=1,
            manifest=manifest(),
            registry=registry,
            error_handler=lambda w, s, err: received_errors.append(err),
        )
        registry.register(30, time.monotonic(), 0)
        registry.transition(0, 30, SessionState.REGISTERING, time.monotonic())
        registry.transition(0, 30, SessionState.PROVISIONING, time.monotonic())
        registry.transition(0, 30, SessionState.SHARD_READY, time.monotonic())

        validator = ConnectionProtocolValidator(inbound_peer=PeerRole.WORKER)
        validator.bind(30, 0)
        validator.set_phase(ConnectionPhase.SHARD_READY)

        server_sock, client_sock = socket.socketpair()
        try:
            conn = _Connection(
                sock=server_sock,
                session_id=30,
                worker_id=0,
                validator=validator,
                assembler=TensorTransferAssembler(
                    manifest(), max_model_bytes=12, max_tensor_chunk_bytes=8
                ),
                sender=LogicalTransferSender(lambda s, f: None),
                last_seen=time.monotonic(),
            )
            server._connections[0] = conn

            reader_error: list[Exception] = []

            def run_reader() -> None:
                try:
                    server._read_bound(conn)
                except Exception as exc:
                    reader_error.append(exc)

            read_thread = threading.Thread(target=run_reader, daemon=True)
            read_thread.start()

            # Send fatal SESSION scope ERROR
            fatal_err = Error.from_dict(
                {
                    "error_code": "CUDA_OOM",
                    "scope": "SESSION",
                    "severity": "ERROR",
                    "message": "Out of GPU memory",
                    "retryable": False,
                }
            )
            frame = build_control_frame(fatal_err, session_id=30, worker_id=0)
            frame.write_to(client_sock, lambda s, b: s.sendall(b))

            read_thread.join(timeout=2.0)
            self.assertEqual(len(received_errors), 1)
            self.assertEqual(received_errors[0].error_code, "CUDA_OOM")
            self.assertTrue(reader_error)
            self.assertIsInstance(reader_error[0], ProtocolError)
            self.assertIn("Fatal worker error", str(reader_error[0]))

            # Worker session MUST be transitioned to FAILED with failure_code
            session = registry.snapshot()[0]
            self.assertEqual(session.state, SessionState.FAILED)
            self.assertEqual(session.failure_code, "CUDA_OOM")
            self.assertEqual(conn.validator.phase, ConnectionPhase.CLOSED)
        finally:
            server_sock.close()
            client_sock.close()

    def test_worker_client_handles_fatal_error_from_server(self) -> None:
        import socket

        from pbl4.protocol.codec import DTPFrame
        from pbl4.protocol.messages import DtpControlMessage, build_control_frame
        from pbl4.transport.framed_socket import recv_exact
        from pbl4.worker.worker_client import WorkerClient

        server_sock, client_sock = socket.socketpair()
        received_messages: list[DtpControlMessage] = []
        try:
            client = WorkerClient(
                "127.0.0.1",
                0,
                node_label="worker-err-test",
                manifest=manifest(),
                message_handler=lambda msg, op: received_messages.append(msg),
            )
            # Bind fake transport and connection
            client._transport._sock = client_sock
            client.session_id = 40
            client.worker_id = 0
            client.attempt_id = "attempt-worker-err"
            client.job_id = "job-worker-err"
            client.expected_workers = 1
            client.max_tensor_chunk_bytes = 1024
            client._validator.bind(40, 0)
            client._closing.clear()
            client._reader = threading.Thread(target=client._read_loop, daemon=True)
            client._reader.start()

            # Test client.send_error
            client.send_error(
                Error.from_dict(
                    {
                        "error_code": "LOCAL_CRASH",
                        "scope": "SESSION",
                        "severity": "CRITICAL",
                        "message": "Process shutting down",
                        "retryable": False,
                    }
                )
            )
            echo_frame = DTPFrame.read_from(
                server_sock,
                recv_exact,
                bound_identity=(40, 0),
            )
            self.assertEqual(echo_frame.header.message_type, 0x00FF)
            decoded = decode_control_message(echo_frame.header.message_type, echo_frame.payload)
            self.assertEqual(decoded.error_code, "LOCAL_CRASH")

            # Server sends fatal ERROR to worker
            fatal_err = Error.from_dict(
                {
                    "error_code": "ATTEMPT_ABORTED",
                    "scope": "ATTEMPT",
                    "severity": "CRITICAL",
                    "message": "Attempt aborted by runtime",
                    "retryable": False,
                }
            )
            frame = build_control_frame(fatal_err, session_id=40, worker_id=0)
            frame.write_to(server_sock, lambda s, b: s.sendall(b))

            client._reader.join(timeout=2.0)
            self.assertEqual(len(received_messages), 1)
            self.assertEqual(received_messages[0].error_code, "ATTEMPT_ABORTED")
            self.assertTrue(client._closing.is_set())
            self.assertEqual(client._validator.phase, ConnectionPhase.CLOSED)
        finally:
            server_sock.close()
            client_sock.close()

    def test_parameter_server_send_error(self) -> None:
        import socket

        from pbl4.protocol.codec import DTPFrame
        from pbl4.runtime.parameter_server import ParameterServer, _Connection
        from pbl4.runtime.worker_registry import WorkerRegistry
        from pbl4.transport.framed_socket import recv_exact

        server_sock, client_sock = socket.socketpair()
        try:
            registry = WorkerRegistry("attempt-send-err", 1)
            server = ParameterServer(
                "127.0.0.1",
                0,
                attempt_id="attempt-send-err",
                job_id="job-send-err",
                expected_workers=1,
                manifest=manifest(),
                registry=registry,
            )
            validator = ConnectionProtocolValidator(inbound_peer=PeerRole.WORKER)
            validator.bind(50, 0)
            conn = _Connection(
                sock=server_sock,
                session_id=50,
                worker_id=0,
                validator=validator,
                assembler=TensorTransferAssembler(
                    manifest(), max_model_bytes=12, max_tensor_chunk_bytes=8
                ),
                sender=LogicalTransferSender(
                    lambda s, f: f.write_to(s, lambda sk, b: sk.sendall(b))
                ),
                last_seen=time.monotonic(),
            )
            server._connections[0] = conn

            err = Error.from_dict(
                {
                    "error_code": "MANIFEST_MISMATCH",
                    "scope": "SESSION",
                    "severity": "ERROR",
                    "message": "Manifest checksum mismatch",
                    "retryable": False,
                }
            )
            server.send_error(0, err)

            rec = DTPFrame.read_from(client_sock, recv_exact, bound_identity=(50, 0))
            self.assertEqual(rec.header.message_type, 0x00FF)
            msg = decode_control_message(rec.header.message_type, rec.payload)
            self.assertEqual(msg.error_code, "MANIFEST_MISMATCH")
            self.assertEqual(msg.scope, "SESSION")
        finally:
            server_sock.close()
            client_sock.close()


if __name__ == "__main__":
    unittest.main()
