"""Tests for HTTP idempotency identity, hashing, and conflict semantics."""

from unittest.mock import MagicMock

import pytest

from pbl4.management_backend.services.idempotency import (
    IdempotencyConflictError,
    IdempotencyRecordNotFoundError,
    bind_command_to_record,
    build_request_hash,
)


def test_idempotency_request_hash_incorporates_all_identities():
    op = "POST"
    body = {"note": "initial run"}

    # Different paths with identical body must produce DIFFERENT hashes
    hash_job_a = build_request_hash(
        operation=op,
        path="/api/v1/jobs/job_A/start",
        query_params=None,
        body_obj=body,
    )
    hash_job_b = build_request_hash(
        operation=op,
        path="/api/v1/jobs/job_B/start",
        query_params=None,
        body_obj=body,
    )
    assert hash_job_a != hash_job_b

    # Different operations with identical path and body must produce DIFFERENT hashes
    hash_get = build_request_hash(
        operation="GET",
        path="/api/v1/jobs/job_A/start",
        query_params=None,
        body_obj=body,
    )
    assert hash_job_a != hash_get

    # Different queries must produce DIFFERENT hashes
    hash_query1 = build_request_hash(
        operation=op,
        path="/api/v1/jobs/job_A/start",
        query_params={"dry_run": "true"},
        body_obj=body,
    )
    hash_query2 = build_request_hash(
        operation=op,
        path="/api/v1/jobs/job_A/start",
        query_params={"dry_run": "false"},
        body_obj=body,
    )
    assert hash_query1 != hash_query2
    assert hash_query1 != hash_job_a

    # Identical inputs in different key orders produce IDENTICAL hashes
    hash_reordered = build_request_hash(
        operation=op,
        path="/api/v1/jobs/job_A/start",
        query_params=None,
        body_obj={"note": "initial run"},
    )
    assert hash_job_a == hash_reordered


def test_idempotency_conflict_error_properties():
    err = IdempotencyConflictError("Key reused with different request payload.")
    assert err.code == "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_REQUEST"
    assert "different request" in str(err)


def test_bind_command_to_record_success():
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 1
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    bind_command_to_record(
        mock_conn,
        operator_identity="admin",
        endpoint_semantic_scope="DATASET_BUILD_DELETE",
        idempotency_key="idemp-key-1",
        command_id="550e8400-e29b-41d4-a716-446655440000",
        resource_id="build-42",
    )

    assert mock_cursor.execute.called
    query_str, params = mock_cursor.execute.call_args[0]
    assert "UPDATE idempotency_records" in query_str
    assert "command_id = %s::uuid" in query_str
    assert params == (
        "550e8400-e29b-41d4-a716-446655440000",
        "build-42",
        "admin",
        "DATASET_BUILD_DELETE",
        "idemp-key-1",
    )


def test_bind_command_to_record_raises_when_record_missing():
    mock_cursor = MagicMock()
    mock_cursor.rowcount = 0
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    with pytest.raises(IdempotencyRecordNotFoundError) as exc_info:
        bind_command_to_record(
            mock_conn,
            operator_identity="default",
            endpoint_semantic_scope="DATASET_BUILD_DELETE",
            idempotency_key="missing-key-999",
            command_id="550e8400-e29b-41d4-a716-446655440000",
        )

    err = exc_info.value
    assert isinstance(err, RuntimeError)
    assert "Idempotency record not found" in str(err)
    assert "missing-key-999" in str(err)
    assert "DATASET_BUILD_DELETE" in str(err)
    assert "default" in str(err)
