"""Real PostgreSQL existing schema/retention/locking in disposable schemas only."""

import importlib.util
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from psycopg import sql
from sqlalchemy import create_engine

from pbl4.management_backend.repositories import checkpoint_repository as repository

ALL_CHECKPOINT_IDS = [f"c{i}" for i in range(6)]


@pytest.fixture
def database():
    dsn = os.getenv("TEST_DATABASE_URL") or "postgresql://postgres:123456@localhost:5432/pbl4_test"
    try:
        admin = psycopg.connect(dsn, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL test database unavailable")
    schema = "checkpoint_test_" + uuid4().hex
    admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    engine = create_engine(
        "postgresql+psycopg://",
        creator=lambda: psycopg.connect(dsn, options=f"-csearch_path={schema}"),
    )
    try:
        # Exercise the actual migration chain, without touching public tables.
        with (
            engine.begin() as connection,
            Operations.context(MigrationContext.configure(connection)),
        ):
            for path in sorted(Path("migrations/versions").glob("*.py")):
                spec = importlib.util.spec_from_file_location(path.stem, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.upgrade()

        @contextmanager
        def connect():
            with psycopg.connect(dsn, autocommit=True, options=f"-csearch_path={schema}") as conn:
                conn.execute("SET statement_timeout = '8s'")
                yield conn

        yield connect
    finally:
        engine.dispose()
        admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        admin.close()


def populate(conn, *, checkpoints=True):
    # Minimal valid Job/Attempt records; actual migration constraints stay enabled.
    conn.execute(
        """
        INSERT INTO jobs (job_id, display_name, description, state, requested_contract,
                          resolved_contract,
                          contract_hash, created_at)
        VALUES ('job', 'Checkpoint test', '', 'DRAFT', '{}', '{}', %s, now())
    """,
        ("a" * 64,),
    )
    conn.execute(
        """
        INSERT INTO attempts (attempt_id, job_id, contract_hash, execution_mode, state, created_at)
        VALUES ('attempt', 'job', %s, 'FRESH', 'COMPLETED', now())
    """,
        ("a" * 64,),
    )
    conn.execute("""
        INSERT INTO datasets (dataset_id, name, task_type, source_type,
                              source_reference, created_at)
        VALUES ('dataset', 'Test dataset', 'image_classification',
                'LOCAL_DIRECTORY', 'test://dataset', now())
    """)
    conn.execute("""
        INSERT INTO dataset_builds (
            dataset_build_id, dataset_id, state, profile, batch_size, shard_count,
            num_classes, input_shape_json, dtype, preprocessing_json, partition_seed, created_at
        ) VALUES ('build', 'dataset', 'CREATED', 'TEST', 1, 1, 10, '[3,32,32]',
                  'float32', '{}', 0, now())
    """)
    if not checkpoints:
        return
    for i in range(6):
        repository.create_checkpoint(
            conn,
            checkpoint_id=f"c{i}",
            created_by_attempt_id="attempt",
            source_operation_id=i,
            model_version=100 - i,
            recovery_cursor_jsonb={"epoch": i, "next_batch_ordinal": 0},
            contract_hash="a" * 64,
            dataset_manifest_hash="b" * 64,
            parameter_manifest_hash="c" * 64,
            checkpoint_policy="periodic",
            checkpoint_policy_version=1,
            created_at=f"2026-11-02T00:00:0{i}Z",
        )
    conn.execute("UPDATE checkpoints SET dataset_build_id = 'build'")
    for i in range(6):
        repository.complete_checkpoint(
            conn,
            f"c{i}",
            model_path="model.bin",
            metadata_path="checkpoint.json",
            model_sha256="d" * 64,
            metadata_sha256="e" * 64,
            completed_at=f"2026-11-02T00:00:0{i}Z",
        )


def test_retention_preserves_three_newest_and_references(database):
    with database() as conn:
        populate(conn)
        conn.execute(
            """
            INSERT INTO attempts (attempt_id, job_id, contract_hash, execution_mode, state,
                                  resume_from_checkpoint_id, created_at)
            VALUES ('resumed', 'job', %s, 'RESUME', 'COMPLETED', 'c0', now())
        """,
            ("a" * 64,),
        )
        assert [
            r["checkpoint_id"] for r in repository.retention_candidates(conn, 3, ALL_CHECKPOINT_IDS)
        ] == [
            "c1",
            "c2",
        ]
        repository.confirm_artifact_deleted(conn, "c0")
        repository.confirm_artifact_deleted(conn, "c5")
        assert repository.get_checkpoint(conn, "c0") is not None
        assert repository.get_checkpoint(conn, "c5") is not None
        with conn.transaction():
            assert repository.retire_artifact(conn, "c1", 3, ALL_CHECKPOINT_IDS)
            assert not repository.retire_artifact(conn, "c0", 3, ALL_CHECKPOINT_IDS)
            assert not repository.retire_artifact(conn, "c5", 3, ALL_CHECKPOINT_IDS)
        assert repository.get_checkpoint(conn, "c1")["artifact_retired"]
        assert "c1" not in {r["checkpoint_id"] for r in repository.list_checkpoints(conn)}
        # Replay cannot remove the separate tombstone.
        repository.complete_checkpoint(
            conn,
            "c1",
            model_path="model.bin",
            metadata_path="checkpoint.json",
            model_sha256="d" * 64,
            metadata_sha256="e" * 64,
            completed_at="2026-11-02T01:00:00Z",
        )
        assert repository.get_checkpoint(conn, "c1")["artifact_retired"]
        assert len(repository.pending_artifact_deletions(conn)) == 1
        repository.confirm_artifact_deleted(conn, "c1")
        assert repository.pending_artifact_deletions(conn) == []


def test_reference_transaction_wins_concurrent_retirement(database):
    with database() as conn:
        populate(conn)
    started = threading.Event()
    result, errors = [], []

    def retire():
        try:
            with database() as other, other.transaction():
                started.set()
                result.append(repository.retire_artifact(other, "c0", 3, ALL_CHECKPOINT_IDS))
        except Exception as exc:
            errors.append(exc)

    with database() as conn, conn.transaction():
        repository.get_checkpoint(conn, "c0", for_update=True)
        worker = threading.Thread(target=retire)
        worker.start()
        assert started.wait(3)
        conn.execute(
            """
            INSERT INTO attempts (attempt_id, job_id, contract_hash, execution_mode, state,
                                  resume_from_checkpoint_id, created_at)
            VALUES ('race-resume', 'job', %s, 'RESUME', 'COMPLETED', 'c0', now())
        """,
            ("a" * 64,),
        )
    worker.join(10)
    assert not worker.is_alive()
    assert not errors
    assert result == [False]


def test_retirement_wins_and_resume_service_refuses_source(database):
    from pbl4.management_backend.services.attempt_service import (
        CheckpointNotCompleteError,
        resume_job,
    )

    with database() as conn:
        populate(conn)
        conn.execute("UPDATE jobs SET state = 'READY', frozen_at = now()")
        with conn.transaction():
            assert repository.retire_artifact(conn, "c0", 3, ALL_CHECKPOINT_IDS)
        with pytest.raises(CheckpointNotCompleteError):
            resume_job(conn, "job", "c0")
        assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1


def test_runtime_backend_retention_and_download_roundtrip(database, tmp_path, monkeypatch):
    from dataclasses import replace

    import httpx
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from psycopg.types.json import Jsonb

    from pbl4.management_backend import config, db
    from pbl4.management_backend.api.checkpoints import router
    from pbl4.management_backend.config import BackendSettings
    from pbl4.management_backend.services.checkpoint_artifacts import maintain_checkpoints
    from pbl4.runtime.artifact_http import ArtifactHTTP
    from pbl4.runtime.checkpoint import CheckpointManager
    from pbl4.runtime.checkpoint_v1 import CheckpointV1Serializer
    from tests.unit.test_checkpoint_artifacts import make_artifact

    owner, _, contract, _, original = make_artifact(tmp_path, checkpoint_id="c0")
    manager = CheckpointManager(original.directory.parent, CheckpointV1Serializer())
    for i in range(1, 6):
        manager.write(
            replace(
                original.snapshot,
                checkpoint_id=f"c{i}",
                created_at=f"2026-11-02T00:00:{i + 1:02d}Z",
            )
        )
    inventory = owner.inventory()["items"]
    with database() as conn:
        populate(conn, checkpoints=False)
        conn.execute(
            "UPDATE jobs SET resolved_contract = %s, contract_hash = %s",
            (Jsonb(contract), original.snapshot.contract_hash),
        )
    monkeypatch.setattr(db, "get_connection", database)
    from pbl4.common.hashing import derive_model_artifact_token

    shared_secret = "existing-backend-runtime-test-key"
    server = ArtifactHTTP("127.0.0.1", 0, derive_model_artifact_token(shared_secret), owner)
    server.start()
    artifact_url = f"http://127.0.0.1:{server.address[1]}"
    monkeypatch.setattr(
        BackendSettings, "runtime_artifact_url", property(lambda self: artifact_url)
    )
    # Stale knobs from an older .env must not alter the fixed user-approved policy.
    monkeypatch.setenv("CHECKPOINT_KEEP_LATEST", "1")
    monkeypatch.setenv("CHECKPOINT_RETENTION_DRY_RUN", "true")
    settings = BackendSettings(
        _env_file=None,
        runtime_host="127.0.0.1",
        PBL4_WORKER_ADMISSION_SECRET=shared_secret,
    )
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    try:
        maintain_checkpoints(settings, dry_run=True)
        assert len(owner.inventory()["items"]) == 6
        maintain_checkpoints(settings)
        assert {r["checkpoint_id"] for r in owner.inventory()["items"]} == {"c3", "c4", "c5"}
        with database() as conn:
            assert conn.execute("SELECT count(*) FROM checkpoints").fetchone()[0] == 3
            assert (
                conn.execute(
                    "SELECT count(*) FROM events WHERE event_type = 'checkpoint.artifact.retired'"
                ).fetchone()[0]
                == 3
            )
            repository.reconcile_artifacts(conn, tuple(inventory))
            assert len(repository.list_checkpoints(conn)) == 3
        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as client:
            response = client.get("/api/v1/checkpoints/c5/model")
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/zip"
            assert len(response.content) == int(response.headers["content-length"])
            bundle = tmp_path / "download.zip"
            bundle.write_bytes(response.content)
            from pbl4.adapter.model_export import load_exported_model

            assert load_exported_model(bundle).training is False
            detail = client.get("/api/v1/checkpoints/c5")
            assert detail.status_code == 200
            assert "artifact_retired_at" not in detail.json()["data"]
            assert "artifact_retired" not in detail.json()["data"]
            listing = client.get("/api/v1/checkpoints")
            assert listing.status_code == 200
            assert all("artifact_retired_at" not in item for item in listing.json()["data"])
            assert all("artifact_retired" not in item for item in listing.json()["data"])
            assert client.get("/api/v1/checkpoints/c0/model").status_code == 404
            assert client.get("/api/v1/checkpoints/missing/model").status_code == 404
            with database() as conn, conn.transaction():
                assert repository.retire_artifact(conn, "c3", 1, ALL_CHECKPOINT_IDS)
            assert client.get("/api/v1/checkpoints/c3").status_code == 404
            assert client.get("/api/v1/checkpoints/c3/model").status_code == 409
            model_path = owner._directory("attempt", "c5") / "model.bin"
            original_bytes = model_path.read_bytes()
            model_path.write_bytes(b"corrupt")
            assert client.get("/api/v1/checkpoints/c5/model").status_code == 409
            model_path.write_bytes(original_bytes)
            with monkeypatch.context() as patch:
                patch.setattr(
                    config,
                    "get_settings",
                    lambda: BackendSettings(_env_file=None, PBL4_WORKER_ADMISSION_SECRET=""),
                )
                assert client.get("/api/v1/checkpoints/c5/model").status_code == 503
        # Backend downtime cannot affect the Runtime storage writer.
        server.stop()
        server = None
        with TestClient(app) as client:
            assert client.get("/api/v1/checkpoints/c5/model").status_code == 503
        manager.write(replace(original.snapshot, checkpoint_id="during-outage"))
        with pytest.raises(httpx.HTTPError):
            maintain_checkpoints(settings)
        assert len(owner.inventory()["items"]) == 4
    finally:
        if server is not None:
            server.stop()


def test_waiting_resume_observes_retirement_after_lock_is_released(database, monkeypatch):
    import time

    from pbl4.management_backend.services import attempt_service

    with database() as conn:
        populate(conn)
        conn.execute("UPDATE jobs SET state = 'READY', frozen_at = now()")
    monkeypatch.setattr(attempt_service, "_preflight_job_and_select_placements", lambda *_: [])
    errors = []
    label = "checkpoint_race_" + uuid4().hex

    def resume():
        try:
            with database() as other:
                other.execute("SELECT set_config('application_name', %s, false)", (label,))
                attempt_service.resume_job(other, "job", "c0")
        except Exception as exc:
            errors.append(exc)

    with database() as conn, conn.transaction():
        assert repository.retire_artifact(conn, "c0", 3, ALL_CHECKPOINT_IDS)
        worker = threading.Thread(target=resume)
        worker.start()
        # Observe the blocked SQL transaction rather than guessing via a sleep.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            waiting = conn.execute(
                "SELECT 1 FROM pg_stat_activity WHERE application_name = %s "
                "AND wait_event_type = 'Lock'",
                (label,),
            ).fetchone()
            if waiting:
                break
            conn.execute("SELECT pg_stat_clear_snapshot()")
        assert waiting, "Resume must reach the row lock while retirement is uncommitted"
    worker.join(10)
    assert not worker.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], attempt_service.CheckpointNotCompleteError)
    with database() as conn:
        assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1


def test_retention_counts_verified_physical_inventory_not_stale_index_rows(database):
    with database() as conn:
        populate(conn)
        ids = [f"c{i}" for i in range(5)]  # c5 exists in DB but has no verified artifact.
        assert repository.retention_candidates(conn, 3, []) == []
        assert [r["checkpoint_id"] for r in repository.retention_candidates(conn, 3, ids)] == [
            "c0",
            "c1",
        ]


def test_retirement_rechecks_verified_keep_set_after_another_maintenance(database):
    with database() as conn:
        populate(conn)
        verified_ids = [f"c{i}" for i in range(5)]
        assert [
            r["checkpoint_id"] for r in repository.retention_candidates(conn, 3, verified_ids)
        ] == [
            "c0",
            "c1",
        ]
        # Another maintenance observed c5 and retired c2 before this batch takes its locks.
        with conn.transaction():
            assert repository.retire_artifact(conn, "c2", 3, ALL_CHECKPOINT_IDS)
        with conn.transaction():
            assert repository.retire_artifact(conn, "c0", 3, verified_ids)
        with conn.transaction():
            assert not repository.retire_artifact(conn, "c1", 3, verified_ids)
        assert {
            row["checkpoint_id"]
            for row in repository.list_checkpoints(conn)
            if row["checkpoint_id"] in verified_ids
        } == {"c1", "c3", "c4"}


def test_bulk_reconcile_reuses_complete_rows_without_writes(database):
    with database() as conn:
        populate(conn)
        items = tuple(
            {
                "checkpoint_id": f"c{i}",
                "metadata": {
                    "created_by_attempt_id": "attempt",
                    "contract_hash": "a" * 64,
                },
                "model_sha256": "d" * 64,
                "metadata_sha256": "e" * 64,
            }
            for i in range(6)
        )
        before = conn.execute(
            "SELECT checkpoint_id, xmin::text FROM checkpoints ORDER BY checkpoint_id"
        ).fetchall()
        repository.reconcile_artifacts(conn, items)
        assert (
            conn.execute(
                "SELECT checkpoint_id, xmin::text FROM checkpoints ORDER BY checkpoint_id"
            ).fetchall()
            == before
        )
        with pytest.raises(ValueError, match="identity conflict"):
            repository.reconcile_artifacts(conn, ({**items[0], "model_sha256": "f" * 64},))
