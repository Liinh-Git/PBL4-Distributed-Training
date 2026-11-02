"""Published checkpoint artifacts; independent of the training coordinator.

Export completed model bundles without decoding their tensor payloads.
No framework execution or management/database call belongs in this owner.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import tempfile
import threading
import time
import zipfile
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from pbl4.common.hashing import canonical_json_bytes, canonical_json_hash, sha256_bytes, sha256_file
from pbl4.protocol.parameter_manifest import ParameterManifest
from pbl4.runtime.checkpoint import CheckpointManager

logger = logging.getLogger(__name__)
_VERIFY_CACHE_SECONDS = 300
_VERIFY_CACHE_LIMIT = 256
_COPY_BYTES = 1024 * 1024
_IDENTITY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class CheckpointArtifacts:
    def __init__(
        self,
        root: Path,
        manifests: list[ParameterManifest],
        protected_ids: Callable[[], set[str]] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self._protected_ids = protected_ids or set
        self._manifests = {m.parameter_manifest_hash: m for m in manifests}
        # Only artifact operations share this lock; checkpoint writes never acquire it.
        self._lock = threading.Lock()
        self._verified: OrderedDict[Path, tuple[tuple, float]] = OrderedDict()

    def _directory(self, attempt_id: str, checkpoint_id: str) -> Path:
        if not all(_IDENTITY.fullmatch(v) for v in (attempt_id, checkpoint_id)):
            raise ValueError("Invalid checkpoint identity")
        directory = self.root / attempt_id / sha256_bytes(checkpoint_id.encode())
        if directory.parent.is_symlink() or directory.is_symlink():
            raise ValueError("Checkpoint symlinks are not allowed")
        if directory.resolve().parent.parent != self.root:
            raise ValueError("Checkpoint path escapes root")
        return directory

    def inventory(self, after: str = "", limit: int = 100) -> dict:
        """Only atomically published directories are visible; pagination is lexical."""
        if not 1 <= limit <= 200:
            raise ValueError("Invalid inventory limit")
        entries = []
        with self._lock:
            if self.root.is_dir():
                for attempt in sorted(self.root.iterdir()):
                    if (
                        attempt.name < after.partition("/")[0]
                        or attempt.name.startswith(".")
                        or attempt.is_symlink()
                        or not attempt.is_dir()
                    ):
                        continue
                    for directory in sorted(attempt.iterdir()):
                        key = f"{attempt.name}/{directory.name}"
                        if key <= after or directory.name.startswith("."):
                            continue
                        try:
                            item = self._describe(directory)
                        except (ValueError, OSError, KeyError, TypeError):
                            logger.warning("Ignoring invalid/unpublished checkpoint artifact")
                            continue
                        entries.append((key, item))
                        if len(entries) > limit:
                            return {
                                "items": [v for _, v in entries[:limit]],
                                "next_cursor": entries[limit - 1][0],
                            }
        return {"items": [v for _, v in entries], "next_cursor": None}

    def _describe(self, directory: Path, *, verify_payload: bool = True) -> dict:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Invalid checkpoint directory")
        metadata = directory / "checkpoint.json"
        payload = directory / "model.bin"
        if any(p.is_symlink() or not p.is_file() for p in (metadata, payload)):
            raise ValueError("Checkpoint is not published")
        if metadata.stat().st_size > 1_048_576:
            raise ValueError("Oversized checkpoint metadata")
        raw = metadata.read_bytes()
        value = json.loads(raw)
        if raw != canonical_json_bytes(value):
            raise ValueError("Noncanonical checkpoint metadata")
        if self._directory(value["created_by_attempt_id"], value["checkpoint_id"]) != directory:
            raise ValueError("Checkpoint identity/path mismatch")
        model = value["model"]
        if payload.stat().st_size != model["payload_size_bytes"]:
            raise ValueError("Checkpoint payload size mismatch")
        if verify_payload:
            self._verify_payload(payload, model["payload_sha256"])
        return {
            "checkpoint_id": value["checkpoint_id"],
            "metadata": value,
            "model_sha256": model["payload_sha256"],
            "metadata_sha256": sha256_bytes(raw),
        }

    @staticmethod
    def _fingerprint(path: Path) -> tuple:
        stat = path.stat()
        return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)

    def _verify_payload(self, path: Path, digest: str) -> None:
        fingerprint = self._fingerprint(path)
        signature = (digest, *fingerprint)
        now = time.monotonic()
        cached = self._verified.get(path)
        if cached and cached[0] == signature and now - cached[1] < _VERIFY_CACHE_SECONDS:
            self._verified.move_to_end(path)
            return
        if sha256_file(str(path)) != digest or self._fingerprint(path) != fingerprint:
            self._verified.pop(path, None)
            raise ValueError("Checkpoint payload hash mismatch")
        self._verified[path] = (signature, now)
        self._verified.move_to_end(path)
        if len(self._verified) > _VERIFY_CACHE_LIMIT:
            self._verified.popitem(last=False)

    def _export_directory(self) -> Path:
        directory = self.root / ".exports"
        if directory.is_symlink() or directory.resolve().parent != self.root:
            raise ValueError("Invalid model export directory")
        directory.mkdir(parents=True, exist_ok=True)
        # Reap abandoned exports from crashed processes, never a live short transfer.
        cutoff = time.time() - 86400
        for entry in directory.glob("export-*"):
            if (
                entry.is_dir()
                and not entry.is_symlink()
                and entry.resolve().parent == directory
                and entry.stat().st_mtime < cutoff
            ):
                shutil.rmtree(entry)
        return directory

    @contextmanager
    def export(self, descriptor: dict, contract: dict) -> Iterator[Path]:
        # TemporaryDirectory owns cleanup on disconnect/error as well as success.
        with self._lock:
            export_directory = self._export_directory()
        with tempfile.TemporaryDirectory(prefix="export-", dir=export_directory) as temporary:
            archive = Path(temporary) / "model.zip"
            with self._lock:
                directory = self._directory(
                    descriptor["created_by_attempt_id"], descriptor["checkpoint_id"]
                )
                item = self._describe(directory, verify_payload=False)
                metadata = item["metadata"]
                if any(item[key] != descriptor[key] for key in ("model_sha256", "metadata_sha256")):
                    raise ValueError("Export descriptor hash mismatch")
                if canonical_json_hash(contract) != metadata["contract_hash"]:
                    raise ValueError("Export contract hash mismatch")
                manifest = self._manifests.get(metadata["model"]["parameter_manifest_hash"])
                if (
                    manifest is None
                    or manifest.total_bytes != metadata["model"]["payload_size_bytes"]
                ):
                    raise ValueError("Matching parameter manifest is unavailable")
                with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as bundle:
                    # Hash exactly the bytes written into the ZIP, in one bounded-memory pass.
                    digest = hashlib.sha256()
                    copied = 0
                    with (
                        (directory / "model.bin").open("rb") as source,
                        bundle.open("model.bin", "w", force_zip64=True) as destination,
                    ):
                        while chunk := source.read(_COPY_BYTES):
                            digest.update(chunk)
                            copied += destination.write(chunk)
                    if copied != manifest.total_bytes or digest.hexdigest() != item["model_sha256"]:
                        raise ValueError("Checkpoint payload hash mismatch during export")
                    bundle.writestr("checkpoint.json", canonical_json_bytes(metadata))
                    bundle.writestr(
                        "parameter-manifest.json", canonical_json_bytes(manifest.to_dict())
                    )
                    bundle.writestr("resolved-contract.json", canonical_json_bytes(contract))
                    bundle.writestr(
                        "README.txt",
                        "Install the matching PBL4 checkout with worker dependencies.\n"
                        "from pbl4.adapter.model_export import load_exported_model\n"
                        "model = load_exported_model('model.zip')\n"
                        "Preprocessing is recorded in resolved-contract.json.\n",
                    )
            yield archive

    def purge(self, descriptor: dict) -> None:
        """Idempotent deletion of a descriptor-pinned artifact, never an arbitrary path."""
        with self._lock:
            directory = self._directory(
                descriptor["created_by_attempt_id"], descriptor["checkpoint_id"]
            )
            if not directory.exists():
                return
            if descriptor["checkpoint_id"] in self._protected_ids():
                raise ValueError("Checkpoint is protected by the Runtime")
            # Verify remaining files as well on retry after a partial filesystem deletion.
            for name, digest in (
                ("model.bin", descriptor["model_sha256"]),
                ("checkpoint.json", descriptor["metadata_sha256"]),
            ):
                artifact = directory / name
                if artifact.exists() or artifact.is_symlink():
                    CheckpointManager._verify_file(artifact, artifact.stat().st_size, digest)
            # The resolved directory and its parent have been checked against root.
            shutil.rmtree(directory)
            self._verified.pop(directory / "model.bin", None)
            CheckpointManager._fsync_directory(directory.parent)
