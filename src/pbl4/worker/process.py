"""Production composition for one worker OS process."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Full, Queue

from torch.nn import functional

from pbl4.adapter.models.factory import build_model
from pbl4.adapter.pytorch_adapter import PyTorchAdapter
from pbl4.common.errors import ProtocolError, TransportError
from pbl4.protocol.messages import DatasetAssignment, Error, ShardReady, StepStart, Stop
from pbl4.protocol.transfer import CompletedTensorTransfer
from pbl4.worker.config import WorkerConfig
from pbl4.worker.dataset_cache import DatasetCache
from pbl4.worker.shard_cache import ShardCache, ShardCacheKey
from pbl4.worker.shard_downloader import ShardDownloader
from pbl4.worker.tensor_bundle import flatten_bundle
from pbl4.worker.training_loop import StepAssignment, TrainingLoop
from pbl4.worker.worker_client import WorkerClient

logger = logging.getLogger(__name__)


class WorkerProcess:
    def __init__(
        self,
        config: WorkerConfig,
        *,
        initialization_seed: int,
        model_id: str | None = None,
        device: str = "cpu",
        connect_timeout_seconds: float = 60.0,
        opener: Callable[..., object] | None = None,
    ) -> None:
        self._config = config
        if model_id is None:
            if config.worker_join_token:
                raise ValueError("model_id is required for managed Workers")
            # Preserve the explicit unmanaged/legacy construction path.
            model_id = "resnet18_groupnorm"
        self._adapter = PyTorchAdapter(
            build_model(model_id, initialization_seed=initialization_seed, device=device),
            functional.cross_entropy,
            local_gradient_reduction="mean",
        )
        self._initialization_seed = initialization_seed
        self._connect_timeout = connect_timeout_seconds
        self._opener = opener
        self._stop = threading.Event()
        self._failed = threading.Event()
        self._busy = threading.Event()
        self._lock = threading.Lock()
        self._loop: TrainingLoop | None = None
        self._shard_key: ShardCacheKey | None = None
        self._dataset_cache: DatasetCache | None = None
        self._pending: StepAssignment | None = None
        self._last_operation: int | None = None
        self._last_step: int | None = None
        self._epoch = 0
        self._next_batch_ordinal = 0
        self._client_instance_id = str(uuid.uuid4())
        self._connection_lost = threading.Event()
        self._jobs = Queue(maxsize=2)
        self._asynchronous = False
        self._local_version = 0
        self._reconnect_deadline: float | None = None
        self._client = self._new_client()

    def _new_client(self):
        client = WorkerClient(
            self._config.runtime_host,
            self._config.runtime_port,
            node_label=self._config.node_label,
            manifest=self._adapter.manifest,
            client_instance_id=self._client_instance_id,
            attempt_id=self._config.attempt_id,
            allocation_id=self._config.allocation_id,
            node_id=self._config.node_id,
            worker_join_token=self._config.worker_join_token,
            message_handler=lambda m, op: self._received(client, m, op),
            parameter_handler=lambda t: self._enqueue(client, self._on_parameters, t),
            disconnect_handler=lambda: self._lost(client),
        )

        return client

    def _received(self, client, message, operation):
        if client is not self._client:
            return
        self._asynchronous = client.training_strategy == "async_sgd"
        if isinstance(message, (Stop, Error)):
            self._on_message(message, operation, client=client)
        else:
            self._enqueue(client, self._on_message, message, operation)

    def _enqueue(self, client, callback, *args):
        if client is not self._client or self._stop.is_set():
            return
        try:
            self._jobs.put_nowait((client, callback, args))
        except Full:
            self._failed.set()
            self._stop.set()
            client.disconnect()

    def _work(self):
        while not self._stop.is_set():
            try:
                client, callback, args = self._jobs.get(timeout=0.1)
            except Empty:
                continue
            if client is self._client and client.connected and not self._stop.is_set():
                callback(*args, client=client)

    def _lost(self, client):
        if client is self._client:
            self._asynchronous = client.training_strategy == "async_sgd"
            self._on_disconnect()

    def _mark_ready(self, client):
        if client is self._client and not self._connection_lost.is_set():
            self._reconnect_deadline = None

    @property
    def client_instance_id(self) -> str:
        return self._client_instance_id

    @property
    def dataset_cache(self) -> DatasetCache | None:
        with self._lock:
            return self._dataset_cache

    @property
    def manifest_hash(self) -> str:
        return self._adapter.manifest.parameter_manifest_hash

    def run(self) -> bool:
        processor = threading.Thread(target=self._work, name="worker-compute", daemon=True)
        heartbeat = threading.Thread(
            target=self._heartbeat_loop, name="worker-heartbeat", daemon=True
        )
        processor.start()
        heartbeat.start()
        deadline = time.monotonic() + self._connect_timeout
        delay = 0.5
        try:
            while not self._stop.is_set():
                client = self._client
                self._connection_lost.clear()
                try:
                    ack = client.connect()
                    self._asynchronous = ack.training_strategy == "async_sgd"
                    delay = 0.5
                    while not self._stop.is_set() and not self._connection_lost.wait(0.1):
                        if client.write_timed_out(time.monotonic()):
                            logger.warning("Runtime DTP write stalled; closing the connection")
                            self._lost(client)
                            client.disconnect()
                            break
                        if (
                            self._reconnect_deadline is not None
                            and time.monotonic() >= self._reconnect_deadline
                        ):
                            self._failed.set()
                            self._stop.set()
                except ProtocolError:
                    logger.exception("Runtime rejected the Worker handshake")
                    self._failed.set()
                    self._stop.set()
                except Exception as exc:
                    logger.warning("Runtime connection unavailable (%s)", type(exc).__name__)
                client.disconnect()
                if self._stop.is_set():
                    break
                if time.monotonic() >= (self._reconnect_deadline or deadline):
                    self._failed.set()
                    break
                if self._stop.wait(delay):
                    break
                delay = min(delay * 2, 30.0)
                self._pending = None
                self._client = self._new_client()
        finally:
            self._stop.set()
            self._client.disconnect()
            heartbeat.join(timeout=2)
            processor.join(timeout=2)
            if processor.is_alive():
                logger.error("Worker computation did not stop within the shutdown deadline")
                self._failed.set()
        return not self._failed.is_set()

    def _on_disconnect(self) -> None:
        if not self._stop.is_set():
            if self._asynchronous:
                if self._reconnect_deadline is None:
                    self._reconnect_deadline = time.monotonic() + self._connect_timeout
                self._connection_lost.set()
            else:
                logger.error("Runtime DTP connection closed unexpectedly")
                self._failed.set()
                self._stop.set()

    def _on_message(self, message, operation_id: int, *, client=None) -> None:
        client = client or self._client
        try:
            if isinstance(message, DatasetAssignment):
                self._provision(message, client=client)
            elif isinstance(message, StepStart):
                self._compute(message, operation_id, client=client)
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
        except TransportError:
            self._lost(client)
            client.disconnect()
        except Exception:
            if client is not self._client or self._connection_lost.is_set():
                return
            logger.exception("Worker message processing failed")
            self._failed.set()
            self._stop.set()
            client.disconnect()

    def _provision(self, assignment: DatasetAssignment, *, client=None) -> None:
        client = client or self._client
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
        downloader_kwargs: dict[str, object] = {"timeout_seconds": 60.0}
        if self._opener is not None:
            downloader_kwargs["opener"] = self._opener
        downloader = ShardDownloader(
            str(assignment.artifact_base_url),
            ShardCache(cache_root),
            cache_root / ".downloads",
            root_manifest_path=str(assignment.root_manifest_path),
            **downloader_kwargs,
        )
        result = downloader.provision(key)
        provisioned = {key.shard_id: result}
        dataset_cache: DatasetCache | None = None
        if assignment.cache_scope == "all_shards":
            cached_shards = {key.shard_id: result.shard}
            references = result.shard.root_manifest.get("shards")
            if not isinstance(references, list) or not references:
                raise ValueError("Root Dataset Manifest contains no shards")
            for ref in references:
                if not isinstance(ref, dict) or "shard_id" not in ref:
                    raise ValueError("Root Dataset Manifest contains an invalid shard reference")
                s_id = int(ref["shard_id"])
                if s_id not in cached_shards:
                    s_key = ShardCacheKey(
                        str(assignment.dataset_build_id),
                        str(assignment.dataset_manifest_hash),
                        s_id,
                    )
                    s_result = downloader.provision(s_key)
                    provisioned[s_id] = s_result
                    cached_shards[s_id] = s_result.shard
            dataset_cache = DatasetCache(
                str(assignment.dataset_build_id),
                str(assignment.dataset_manifest_hash),
                cached_shards,
                root_manifest=result.shard.root_manifest,
            )
            dataset_cache.verify_all()

        for s_id, provision in sorted(provisioned.items()):
            logger.info(
                "Dataset cache build_id=%s manifest_hash=%s shard_id=%s cache_reused=%s bytes=%s",
                assignment.dataset_build_id,
                assignment.dataset_manifest_hash,
                s_id,
                provision.cache_reused,
                provision.bytes_downloaded,
            )

        if client is not self._client or self._connection_lost.is_set():
            return
        with self._lock:
            self._loop = TrainingLoop(
                self._adapter,
                dataset_cache if dataset_cache is not None else result.shard,
                0,
            )
            self._shard_key = key
            self._dataset_cache = dataset_cache
        shard_manifest = result.shard.shard_manifest
        root_reference = result.shard.root_manifest["shards"][key.shard_id]
        client.send_shard_ready(
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
        client.send_model_manifest()
        if client.worker_id == 0 and not client.model_initialized:
            client.send_model_init(
                flatten_bundle(self._adapter.export_parameters()),
                initialization_seed=self._initialization_seed,
            )
        logger.info(
            "Shard ready shard_id=%s samples=%s batches=%s cache_reused=%s bytes=%s cache_scope=%s",
            key.shard_id,
            shard_manifest["sample_count"],
            shard_manifest["batch_count"],
            result.cache_reused,
            result.bytes_downloaded,
            assignment.cache_scope,
        )

    def _compute(self, message: StepStart, operation_id: int, *, client=None) -> None:
        client = client or self._client
        self._busy.set()
        try:
            with self._lock:
                loop = self._loop
            if loop is None or client.session_id is None or client.worker_id is None:
                raise ValueError("STEP_START arrived before worker initialization")
            assignment = StepAssignment(
                attempt_id=str(message.attempt_id),
                session_id=client.session_id,
                worker_id=client.worker_id,
                operation_id=operation_id,
                step_id=int(message.step_id),
                input_model_version=int(message.model_version),
                batch_ordinal=int(message.batch_ordinal),
                work_units=message.work_units,
                expected_sample_count=int(message.expected_sample_count),
            )
            t_start = time.perf_counter()
            computed = loop.compute(assignment)
            compute_ms = max((time.perf_counter() - t_start) * 1000.0, 0.001)
            if client is not self._client or self._connection_lost.is_set() or self._stop.is_set():
                self._busy.clear()
                return
            with self._lock:
                self._pending = assignment
                self._epoch = int(message.epoch)
                self._next_batch_ordinal = assignment.batch_ordinal
            client.send_gradient(
                flatten_bundle(computed.local_gradient.bundle),
                operation_id=operation_id,
                model_version=assignment.input_model_version,
                shard_id=assignment.shard_id,
                batch_id=assignment.batch_id,
                batch_ordinal=assignment.batch_ordinal,
                sample_count=computed.local_gradient.sample_count,
                tensor_id=client.worker_id,
                loss=computed.local_gradient.loss,
                compute_ms=compute_ms,
                correct_count=computed.local_gradient.correct_count,
            )
        except Exception:
            self._busy.clear()
            raise

    def _on_parameters(self, transfer: CompletedTensorTransfer, *, client=None) -> None:
        from pbl4.worker.training_flows import async_sgd, sync

        handler = async_sgd if "work_units" in transfer.metadata else sync
        handler.on_parameters(self, client or self._client, transfer)

    def _heartbeat_loop(self) -> None:
        interval = self._config.heartbeat_interval_seconds
        while not self._stop.wait(interval):
            if not self._client.connected:
                continue
            client = self._client
            try:
                with self._lock:
                    version = self._local_version
                    operation = self._last_operation
                    step = self._last_step
                    epoch = self._epoch
                    ordinal = self._next_batch_ordinal
                client.send_heartbeat(
                    local_model_version=version,
                    last_completed_operation_id=operation,
                    worker_state="WAITING",
                    epoch=epoch,
                    next_batch_ordinal=ordinal,
                    last_completed_step_id=step,
                )
            except Exception:
                logger.exception("Heartbeat transmission failed")
                self._lost(client)
                client.disconnect()
