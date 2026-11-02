"""Checkpoint artifact management outside training and runtime-event ingestion."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from itertools import batched

from pbl4.management_backend import db
from pbl4.management_backend.clients.runtime_artifacts import RuntimeArtifacts
from pbl4.management_backend.repositories import checkpoint_repository as repository

logger = logging.getLogger(__name__)
# User-approved retention; these are not deployment/training-contract settings.
KEEP_LATEST = 3
MAINTENANCE_INTERVAL_SECONDS = 30


def artifact_client(settings):
    return RuntimeArtifacts(settings.runtime_artifact_url, settings.runtime_artifact_token)


def descriptor(row: dict) -> dict:
    return {
        key: row[key]
        for key in ("checkpoint_id", "created_by_attempt_id", "model_sha256", "metadata_sha256")
    }


def maintain_checkpoints(settings, *, dry_run: bool = False):
    """Reconcile, retire, then purge; network I/O never holds a DB transaction."""
    with artifact_client(settings) as client:
        # Complete inventory must succeed before selecting deletion candidates.
        available_ids = []
        for page in batched(client.inventory(), 100):
            available_ids.extend(item["checkpoint_id"] for item in page)
            with db.get_connection() as conn, conn.transaction():
                repository.reconcile_artifacts(conn, page)
        with db.get_connection() as conn:
            candidates = repository.retention_candidates(conn, KEEP_LATEST, available_ids)
        if dry_run:
            logger.info(
                "Checkpoint retention dry-run candidates: %s",
                [row["checkpoint_id"] for row in candidates],
            )
            return
        for row in candidates:
            with db.get_connection() as conn, conn.transaction():
                repository.retire_artifact(conn, row["checkpoint_id"], KEEP_LATEST, available_ids)
        with db.get_connection() as conn:
            pending = repository.pending_artifact_deletions(conn)
        for row in pending:
            try:
                client.purge(descriptor(row))
                with db.get_connection() as conn, conn.transaction():
                    repository.confirm_artifact_deleted(conn, row["checkpoint_id"])
            except Exception:
                logger.exception("Checkpoint artifact purge deferred for %s", row["checkpoint_id"])


async def maintenance_loop(settings):
    while True:
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
        work = asyncio.create_task(asyncio.to_thread(maintain_checkpoints, settings))
        try:
            await asyncio.shield(work)
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await work
            raise
        except Exception:
            logger.exception("Checkpoint maintenance deferred; training is unaffected")
