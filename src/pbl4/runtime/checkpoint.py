"""Atomic checkpoint mechanics with an explicitly supplied serialization contract.

CB-02: no concrete V1 payload serializer is selected here. Production composition
must supply the approved serializer once its canonical representation is resolved.
"""

import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from uuid import uuid4

from pbl4.common.hashing import sha256_bytes, sha256_file
from pbl4.runtime.snapshot import CheckpointSnapshot


class CheckpointSerializer(ABC):
    """Owner of the resolved payload/metadata representation and schema versions.

    Implementations must bind model SHA/size and metadata integrity, preserve all
    snapshot fields, and reject unsupported versions and malformed recovery data.
    The same interface permits a deliberately test-only serializer in tests.
    """

    @abstractmethod
    def serialize(self, snapshot: CheckpointSnapshot) -> tuple[bytes, bytes]:
        """Return model payload and integrity-protected checkpoint metadata."""
        ...

    @abstractmethod
    def deserialize(self, payload: bytes, metadata: bytes) -> CheckpointSnapshot:
        """Verify metadata/payload integrity and reconstruct a complete revision."""
        ...


@dataclass(frozen=True, slots=True)
class CompleteCheckpoint:
    snapshot: CheckpointSnapshot
    directory: Path
    model_sha256: str
    metadata_sha256: str
    model_size: int
    metadata_size: int

    @property
    def state(self) -> str:
        return "COMPLETE"


class CheckpointManager:
    """One filesystem write per manager, without holding Coordinator state locks."""

    def __init__(self, root: Path, serializer: CheckpointSerializer):
        self._root = Path(root).resolve()
        self._serializer = serializer
        self._lock = Lock()

    def write(self, snapshot: CheckpointSnapshot) -> CompleteCheckpoint:
        with self._lock:
            payload, metadata = self._serializer.serialize(snapshot)
            if not payload or not metadata:
                raise ValueError("Empty checkpoint representation")
            if self._serializer.deserialize(payload, metadata) != snapshot:
                raise ValueError("Serializer did not preserve the immutable revision")
            self._root.mkdir(parents=True, exist_ok=True)
            # Opaque resource IDs never become filesystem path syntax.
            directory = self._root / sha256_bytes(snapshot.checkpoint_id.encode("utf-8"))
            receipt = CompleteCheckpoint(
                snapshot,
                directory,
                sha256_bytes(payload),
                sha256_bytes(metadata),
                len(payload),
                len(metadata),
            )
            if directory.exists():
                self.verify(receipt)
                self._fsync_directory(directory)
                self._fsync_directory(self._root)
                return receipt
            temporary = self._root / (".tmp-" + uuid4().hex)
            temporary.mkdir()
            try:
                self._write_file(temporary / "model.bin", payload)
                self._verify_file(temporary / "model.bin", len(payload), receipt.model_sha256)
                self._write_file(temporary / "checkpoint.json", metadata)
                self._verify_file(
                    temporary / "checkpoint.json", len(metadata), receipt.metadata_sha256
                )
                self._fsync_directory(temporary)
                os.rename(temporary, directory)
                self._fsync_directory(self._root)
                self.verify(receipt)
                return receipt
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _write_file(path: Path, content: bytes) -> None:
        with path.open("xb") as stream:
            written = stream.write(content)
            if written != len(content):
                raise OSError("Short checkpoint write")
            stream.flush()
            os.fsync(stream.fileno())

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        # Windows does not expose POSIX directory fsync through os.open.
        if os.name != "nt":
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)

    @staticmethod
    def _verify_file(path: Path, size: int, digest: str) -> None:
        if path.is_symlink() or not path.is_file():
            raise ValueError("Checkpoint artifact is not a regular file")
        if path.stat().st_size != size or sha256_file(str(path)) != digest:
            raise ValueError("Checkpoint size/hash mismatch")

    def verify(self, checkpoint: CompleteCheckpoint) -> CheckpointSnapshot:
        expected = self._root / sha256_bytes(checkpoint.snapshot.checkpoint_id.encode("utf-8"))
        if checkpoint.directory != expected or expected.is_symlink():
            raise ValueError("Checkpoint path does not belong to this root")
        self._verify_file(expected / "model.bin", checkpoint.model_size, checkpoint.model_sha256)
        self._verify_file(
            expected / "checkpoint.json", checkpoint.metadata_size, checkpoint.metadata_sha256
        )
        restored = self._serializer.deserialize(
            (expected / "model.bin").read_bytes(), (expected / "checkpoint.json").read_bytes()
        )
        if restored != checkpoint.snapshot:
            raise ValueError("Checkpoint metadata/revision mismatch")
        return restored

    def restore(
        self, checkpoint: CompleteCheckpoint, expected: CheckpointSnapshot
    ) -> CheckpointSnapshot:
        """Validate the pinned contract for a NEW Attempt before exposing model bytes.

        The production serializer must supply verified metadata inventory after
        restart. This method does not reconstruct sockets, sessions or barriers.
        """
        restored = self.verify(checkpoint)
        if restored.created_by_attempt_id == expected.created_by_attempt_id:
            raise ValueError("Resume requires a new Attempt")
        for field in (
            "checkpoint_schema_version",
            "job_id",
            "contract_hash",
            "checkpoint_policy",
            "checkpoint_policy_version",
            "training_strategy",
            "dataset_build_id",
            "dataset_manifest_hash",
            "model_id",
            "model_profile",
            "optimizer",
        ):
            if getattr(restored, field) != getattr(expected, field):
                raise ValueError(f"Checkpoint contract mismatch: {field}")
        if (
            restored.model.parameter_manifest_hash != expected.model.parameter_manifest_hash
            or restored.model.parameters.shape != expected.model.parameters.shape
        ):
            raise ValueError("Checkpoint parameter manifest/layout mismatch")
        cursor = restored.recovery_cursor
        if (
            type(cursor.epoch) is not int
            or type(cursor.next_batch_ordinal) is not int
            or cursor.epoch < 0
            or cursor.next_batch_ordinal < 0
        ):
            raise ValueError("Invalid recovery cursor")
        return restored
