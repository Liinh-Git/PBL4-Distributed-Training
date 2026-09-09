"""Tests for HTTP idempotency identity, hashing, and conflict semantics."""

from __future__ import annotations

from pbl4.management_backend.services.idempotency import (
    IdempotencyConflictError,
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
