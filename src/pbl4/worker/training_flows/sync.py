"""Strict version/application ACK behavior retained from WorkerProcess."""

import logging

from pbl4.common.errors import TransportError
from pbl4.worker.tensor_bundle import bundle_from_bytes

logger = logging.getLogger(__name__)


def on_parameters(worker, client, transfer):
    try:
        target_version = int(transfer.metadata["model_version_out"])
        bundle = bundle_from_bytes(transfer.data, worker._adapter)
        with worker._lock:
            loop = worker._loop
            shard_key = worker._shard_key
            pending = worker._pending
        if loop is None or shard_key is None:
            raise ValueError("Canonical parameters arrived before shard provisioning")
        if pending is None:
            loop.initialize_parameters(target_version, bundle)
            worker._local_version = target_version
            client.send_ready(
                model_version=target_version,
                dataset_build_id=shard_key.dataset_build_id,
                shard_id=shard_key.shard_id,
            )
            worker._mark_ready(client)
            worker._busy.clear()
            return
        eligibility = loop.apply_parameters(pending, target_version, bundle)
        worker._local_version = target_version
        if loop.consume_parameter_applied() != eligibility:
            raise ValueError("Parameter application eligibility changed")
        client.send_parameter_applied(
            operation_id=eligibility.operation_id,
            source_step_id=eligibility.step_id,
            model_version=eligibility.model_version,
        )
        with worker._lock:
            worker._pending = None
            worker._last_operation = eligibility.operation_id
            worker._last_step = eligibility.step_id
            worker._next_batch_ordinal = pending.batch_ordinal + 1
        worker._busy.clear()
        logger.info(
            "Applied canonical parameters step=%s model_version=%s",
            eligibility.step_id,
            eligibility.model_version,
        )
    except TransportError:
        worker._lost(client)
        client.disconnect()
    except Exception:
        if client is not worker._client or worker._connection_lost.is_set():
            return
        logger.exception("Canonical parameter application failed")
        worker._failed.set()
        worker._stop.set()
        client.disconnect()
