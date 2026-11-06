"""Existing StrictBSP scheduling loop, kept independent of async dispatch."""

import time

from pbl4.protocol.messages import StepStart
from pbl4.runtime.coordinator import Coordinator
from pbl4.runtime.heartbeat import HeartbeatMonitor
from pbl4.runtime.parameter_server import ParameterServer


def run_sync(runner, coordinator: Coordinator, server: ParameterServer) -> None:
    monitor = HeartbeatMonitor(runner._registry, runner._process._heartbeat_timeout)
    total_epochs = int(runner._payload["resolved_contract"]["training"]["epochs"])
    while not runner._abort.is_set():
        try:
            operation = coordinator.open_step()
        except StopIteration:
            if not coordinator.has_verified_checkpoint_for_current_revision():
                coordinator.save_checkpoint_for_current_revision(is_final=True)
            coordinator.complete()
            runner._set_state("COMPLETED")
            return
        runner._step_done.clear()
        for assignment in operation.assignments:
            server.send_step_start(
                assignment.worker_id,
                operation.operation_id,
                StepStart.from_dict(
                    {
                        "attempt_id": runner.attempt_id,
                        "epoch": operation.epoch,
                        "step_id": operation.step_id,
                        "batch_ordinal": assignment.batch_ordinal,
                        "model_version": operation.input_model_version,
                        "shard_id": assignment.shard_id,
                        "batch_id": assignment.batch_id,
                        "expected_sample_count": assignment.sample_count,
                        "training_strategy": "strict_bsp",
                        "parameter_manifest_hash": (runner._manifest.parameter_manifest_hash),
                        "work_units": [u.to_dict() for u in assignment.work_units],
                    }
                ),
            )
        deadline = time.monotonic() + 1800.0
        while not runner._step_done.wait(0.2):
            if runner._abort.is_set():
                coordinator.abort()
                return
            for session in monitor.expired(time.monotonic()):
                coordinator.heartbeat_timeout(
                    session.worker_id, session.session_id, session.last_heartbeat_at
                )
            snapshot = coordinator.snapshot()
            if snapshot["state"] in {"FAILED", "ABORTED"}:
                raise RuntimeError(f"Coordinator entered {snapshot['state']}")
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for synchronized Step commit")
        if runner._abort.is_set():
            coordinator.abort()
            return
        snapshot = coordinator.snapshot()
        if snapshot["state"] in {"FAILED", "ABORTED"}:
            raise RuntimeError(f"Coordinator entered {snapshot['state']}")

        current_cursor = coordinator.cursor
        if operation.epoch < current_cursor.epoch < total_epochs:
            completed_epoch = current_cursor.epoch
            if coordinator._checkpoint_policy.due_epoch(completed_epoch):
                coordinator.save_checkpoint_for_current_revision(is_final=False)
