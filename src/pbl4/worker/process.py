"""Production composition for one worker OS process."""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
from torch.nn import functional

from pbl4.adapter.base import TensorBundle
from pbl4.adapter.models.resnet18_gn import build_resnet18_groupnorm
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.protocol.messages import DatasetAssignment, Error, ShardReady, StepStart, Stop
from pbl4.protocol.transfer import CompletedTensorTransfer
from pbl4.worker.config import WorkerConfig
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.shard_downloader import ShardDownloader
from pbl4.worker.training_loop import StepAssignment, TrainingLoop
from pbl4.worker.worker_client import WorkerClient

logger = logging.getLogger(__name__)


def flatten_bundle(bundle: TensorBundle) -> bytes:
    return (
        np.concatenate([value.reshape(-1) for value in bundle.tensors])
        .astype("<f4", copy=False)
        .tobytes()
    )


def bundle_from_bytes(data: bytes, adapter: PyTorchAdapter) -> TensorBundle:
    flat = np.frombuffer(data, dtype="<f4")
    if flat.size != adapter.manifest.total_numel:
        raise ValueError("Canonical parameter transfer has the wrong size")
    tensors = tuple(
        flat[item.byte_offset // 4 : (item.byte_offset + item.byte_length) // 4]
        .reshape(item.shape)
        .astype(np.float32, copy=True)
        for item in adapter.manifest.parameters
    )
    return TensorBundle(adapter.manifest.parameter_manifest_hash, tensors)


class WorkerProcess:
    def __init__(
        self,
        config: WorkerConfig,
        *,
        initialization_seed: int,
        device: str = "cpu",
        connect_timeout_seconds: float = 60.0,
    ) -> None:
        self._config = config
        self._adapter = PyTorchAdapter(
            build_resnet18_groupnorm(initialization_seed=initialization_seed, device=device),
            functional.cross_entropy,
            local_gradient_reduction="mean",
        )
        self._initialization_seed = initialization_seed
        self._connect_timeout = connect_timeout_seconds
        self._stop = threading.Event()
        self._failed = threading.Event()
        self._busy = threading.Event()
        self._lock = threading.Lock()
        self._loop: TrainingLoop | None = None
        self._shard_key: ShardCacheKey | None = None
        self._pending: StepAssignment | None = None
        self._last_operation: int | None = None
        self._last_step: int | None = None
        self._epoch = 0
        self._next_batch_ordinal = 0
        self._client = WorkerClient(
            config.runtime_host,
            config.runtime_port,
            node_label=config.node_label,
            manifest=self._adapter.manifest,
            message_handler=self._on_message,
            parameter_handler=self._on_parameters,
            disconnect_handler=self._on_disconnect,
        )

    @property
    def manifest_hash(self) -> str:
        return self._adapter.manifest.parameter_manifest_hash

    def run(self) -> bool:
        deadline = time.monotonic() + self._connect_timeout
        while True:
            try:
                ack = self._client.connect()
                break
            except Exception as exc:
                self._client.disconnect()
                if time.monotonic() >= deadline:
                    logger.error("Runtime connection failed: %s", exc)
                    return False
                time.sleep(0.5)
        logger.info(
            "Registered with Runtime attempt=%s session=%s worker_id=%s expected_workers=%s",
            ack.attempt_id,
            ack.session_id,
            ack.worker_id,
            ack.expected_workers,
        )
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            name=f"pbl4-worker-{ack.worker_id}-heartbeat",
            daemon=True,
        )
        heartbeat.start()
        self._stop.wait()
        self._client.disconnect()
        heartbeat.join(timeout=2.0)
        return not self._failed.is_set()

    def _on_disconnect(self) -> None:
        if not self._stop.is_set():
            logger.error("Runtime DTP connection closed unexpectedly")
            self._failed.set()
            self._stop.set()

    def _on_message(self, message, operation_id: int) -> None:
        try:
            if isinstance(message, DatasetAssignment):
                self._provision(message)
            elif isinstance(message, StepStart):
                self._compute(message, operation_id)
            elif isinstance(message, Stop):
                logger.info(
                    "Runtime stopped worker: state=%s reason=%s",
                    message.attempt_state,
                    message.reason_code,
                )
                if message.attempt_state != "COMPLETED":
                    self._failed.set()
                self._stop.set()
            elif isinstance(message, Error):
                raise RuntimeError(
                    f"Runtime protocol error: {message.error_code}: {message.message}"
                )
        except Exception:
            logger.exception("Worker message processing failed")
            self._failed.set()
            self._stop.set()
            self._client.disconnect()

    def _provision(self, assignment: DatasetAssignment) -> None:
        if assignment.profile != "CNN_IMAGE_CLASSIFICATION_V1":
            raise ValueError("Unsupported Dataset Build profile")
        if int(assignment.expected_shard_count) != int(self._client.expected_workers or -1):
            raise ValueError("Dataset shard count does not match resolved membership")
        key = ShardCacheKey(
            str(assignment.dataset_build_id),
            str(assignment.dataset_manifest_hash),
            int(assignment.shard_id),
        )
        cache_root = Path(self._config.cache_dir)
        result = ShardDownloader(
            str(assignment.artifact_base_url),
            ShardCache(cache_root),
            cache_root / ".downloads",
            timeout_seconds=60.0,
        ).provision(key)
        with self._lock:
            self._loop = TrainingLoop(self._adapter, result.shard, 0)
            self._shard_key = key
        shard_manifest = result.shard.shard_manifest
        root_reference = result.shard.root_manifest["shards"][key.shard_id]
        self._client.send_shard_ready(
            ShardReady.from_dict(
                {
                    "dataset_build_id": key.dataset_build_id,
                    "dataset_manifest_hash": key.dataset_manifest_hash,
                    "shard_id": key.shard_id,
                    "shard_manifest_hash": root_reference["shard_manifest_sha256"],
                    "verified_batch_count": shard_manifest["batch_count"],
                    "verified_sample_count": shard_manifest["sample_count"],
                    "cache_key": key.directory_key,
                    "completed_at": datetime.now(UTC).isoformat(),
                }
            )
        )
        self._client.send_model_manifest()
        if self._client.worker_id == 0:
            self._client.send_model_init(
                flatten_bundle(self._adapter.export_parameters()),
                initialization_seed=self._initialization_seed,
            )
        logger.info(
            "Shard ready shard_id=%s samples=%s batches=%s cache_reused=%s bytes=%s",
            key.shard_id,
            shard_manifest["sample_count"],
            shard_manifest["batch_count"],
            result.cache_reused,
            result.bytes_downloaded,
        )

    def _compute(self, message: StepStart, operation_id: int) -> None:
        self._busy.set()
        try:
            with self._lock:
                loop = self._loop
            if loop is None or self._client.session_id is None or self._client.worker_id is None:
                raise ValueError("STEP_START arrived before worker initialization")
            assignment = StepAssignment(
                attempt_id=str(message.attempt_id),
                session_id=self._client.session_id,
                worker_id=self._client.worker_id,
                operation_id=operation_id,
                step_id=int(message.step_id),
                input_model_version=int(message.model_version),
                shard_id=int(message.shard_id),
                batch_id=int(message.batch_id),
                batch_ordinal=int(message.batch_ordinal),
                expected_sample_count=int(message.expected_sample_count),
            )
            computed = loop.compute(assignment)
            with self._lock:
                self._pending = assignment
                self._epoch = int(message.epoch)
                self._next_batch_ordinal = assignment.batch_ordinal
            self._client.send_gradient(
                flatten_bundle(computed.local_gradient.bundle),
                operation_id=operation_id,
                model_version=assignment.input_model_version,
                shard_id=assignment.shard_id,
                batch_id=assignment.batch_id,
                batch_ordinal=assignment.batch_ordinal,
                sample_count=computed.local_gradient.sample_count,
                tensor_id=self._client.worker_id,
                loss=computed.local_gradient.loss,
            )
        except Exception:
            self._busy.clear()
            raise

    def _on_parameters(self, transfer: CompletedTensorTransfer) -> None:
        try:
            target_version = int(transfer.metadata["model_version_out"])
            bundle = bundle_from_bytes(transfer.data, self._adapter)
            with self._lock:
                loop = self._loop
                shard_key = self._shard_key
                pending = self._pending
            if loop is None or shard_key is None:
                raise ValueError("Canonical parameters arrived before shard provisioning")
            if target_version == 0 and pending is None:
                self._adapter.apply_parameters(bundle)
                self._client.send_ready(
                    model_version=0,
                    dataset_build_id=shard_key.dataset_build_id,
                    shard_id=shard_key.shard_id,
                )
                self._busy.clear()
                return
            if pending is None:
                raise ValueError("Model update arrived without a pending Step")
            eligibility = loop.apply_parameters(pending, target_version, bundle)
            if loop.consume_parameter_applied() != eligibility:
                raise ValueError("Parameter application eligibility changed")
            self._client.send_parameter_applied(
                operation_id=eligibility.operation_id,
                source_step_id=eligibility.step_id,
                model_version=eligibility.model_version,
            )
            with self._lock:
                self._pending = None
                self._last_operation = eligibility.operation_id
                self._last_step = eligibility.step_id
                self._next_batch_ordinal = pending.batch_ordinal + 1
            self._busy.clear()
            logger.info(
                "Applied canonical parameters step=%s model_version=%s",
                eligibility.step_id,
                eligibility.model_version,
            )
        except Exception:
            logger.exception("Canonical parameter application failed")
            self._failed.set()
            self._stop.set()
            self._client.disconnect()

    def _heartbeat_loop(self) -> None:
        interval = self._config.heartbeat_interval_seconds
        while not self._stop.wait(interval):
            if self._busy.is_set() or not self._client.connected:
                continue
            try:
                with self._lock:
                    loop = self._loop
                    version = loop.local_model_version if loop is not None else 0
                    operation = self._last_operation
                    step = self._last_step
                    epoch = self._epoch
                    ordinal = self._next_batch_ordinal
                self._client.send_heartbeat(
                    local_model_version=version,
                    last_completed_operation_id=operation,
                    worker_state="WAITING",
                    epoch=epoch,
                    next_batch_ordinal=ordinal,
                    last_completed_step_id=step,
                )
            except Exception:
                logger.exception("Heartbeat transmission failed")
                self._failed.set()
                self._stop.set()
                return
