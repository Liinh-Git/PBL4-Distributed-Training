"""Resolve Runtime dataset requests from the durable Backend catalog."""

from __future__ import annotations

import json
from typing import Any

from pbl4.common.errors import ProtocolError
from pbl4.management_backend.repositories import (
    attempt_repository,
    dataset_build_repository,
    job_repository,
)
from pbl4.management_protocol.messages import DatasetBuildResolved, ResolveDatasetBuild


def resolve_dataset_build(conn: Any, request: dict[str, Any]) -> dict[str, object]:
    """Validate Attempt/Job pinning and return canonical catalog location metadata."""
    values = ResolveDatasetBuild.from_dict(request).to_dict()
    attempt = attempt_repository.get_attempt(conn, values["attempt_id"])
    if attempt is None or attempt["job_id"] != values["job_id"]:
        raise ProtocolError("Dataset resolution Attempt/Job identity mismatch")

    job = job_repository.get_job(conn, values["job_id"])
    if job is None:
        raise ProtocolError("Dataset resolution Job does not exist")
    contract = job.get("resolved_contract") or {}
    if isinstance(contract, str):
        contract = json.loads(contract)
    pinned = contract.get("dataset") or {}
    if pinned.get("dataset_build_id") != values["dataset_build_id"]:
        raise ProtocolError("Dataset build is not pinned by the resolved contract")
    if pinned.get("dataset_manifest_hash") != values["expected_dataset_manifest_hash"]:
        raise ProtocolError("Requested dataset hash is not pinned by the resolved contract")

    build = dataset_build_repository.get_build(conn, values["dataset_build_id"])
    if build is None or build.get("state") != "READY":
        raise ProtocolError("Dataset build is not READY in the Backend catalog")
    if build.get("dataset_manifest_hash") != values["expected_dataset_manifest_hash"]:
        raise ProtocolError("Catalog dataset hash does not match the Runtime request")

    return DatasetBuildResolved.from_dict(
        {
            "dataset_build_id": build["dataset_build_id"],
            "state": build["state"],
            "manifest_uri": build.get("manifest_uri"),
            "artifact_base_url": build.get("artifact_base_url"),
            "dataset_manifest_hash": build.get("dataset_manifest_hash"),
            "profile": build.get("profile"),
            "shard_count": build.get("shard_count"),
            "batch_size": build.get("batch_size"),
        }
    ).to_dict()
