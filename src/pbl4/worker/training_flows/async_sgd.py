"""Apply a complete snapshot, acknowledge it, then compute only its assigned work."""

import logging
import time

from pbl4.common.errors import TransportError
from pbl4.common.work_unit import WorkUnitRef
from pbl4.protocol.session import ConnectionPhase
from pbl4.worker.tensor_bundle import bundle_from_bytes, flatten_bundle
from pbl4.worker.training_loop import StepAssignment

logger = logging.getLogger(__name__)


def on_parameters(worker, client, transfer):
    try:
        if worker._stop.is_set() or client is not worker._client:
            return
        loop = worker._loop
        version = int(transfer.metadata["model_version_out"])
        if loop is None or transfer.metadata["attempt_id"] != client.attempt_id:
            raise ValueError("Async parameters arrived before verified provisioning")
        loop.apply_async_parameters(version, bundle_from_bytes(transfer.data, worker._adapter))
        worker._local_version = version
        operation = transfer.identity.operation_id
        client.send_parameter_applied(
            operation_id=operation, source_step_id=None, model_version=version
        )
        worker._mark_ready(client)
        if worker._stop.is_set() or worker._connection_lost.is_set():
            return
        units = tuple(WorkUnitRef.from_dict(u) for u in transfer.metadata["work_units"])
        if not units:
            return
        assignment = StepAssignment(
            client.attempt_id,
            client.session_id,
            client.worker_id,
            operation,
            None,
            version,
            batch_ordinal=operation,
            work_units=units,
        )
        worker._busy.set()
        with worker._lock:
            worker._epoch = int(transfer.metadata["epoch"])
            worker._next_batch_ordinal = operation
        client._validator.set_phase(ConnectionPhase.UPLOADING)
        started = time.perf_counter()
        computed = loop.compute(assignment).local_gradient
        if (
            client is not worker._client
            or worker._connection_lost.is_set()
            or worker._stop.is_set()
        ):
            return
        client.send_gradient(
            flatten_bundle(computed.bundle),
            operation_id=operation,
            model_version=version,
            shard_id=units[0].shard_id,
            batch_id=units[0].batch_id,
            batch_ordinal=operation,
            sample_count=computed.sample_count,
            loss=computed.loss,
            compute_ms=max(0.001, (time.perf_counter() - started) * 1000),
            correct_count=computed.correct_count,
        )
        with worker._lock:
            worker._last_operation = operation
    except TransportError:
        worker._lost(client)
        client.disconnect()
    except Exception:
        if client is worker._client and not worker._connection_lost.is_set():
            logger.exception("Async computation or parameter application failed")
            worker._failed.set()
            worker._stop.set()
            client.disconnect()
    finally:
        worker._busy.clear()
