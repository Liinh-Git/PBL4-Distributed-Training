"""Dataset Manager client — Management Backend HTTP client to Dataset Manager.

CANONICAL REFERENCES:
- 01. Dataset Manager
- 03. API Dataset Manager & Contracts
- 04. Cấu trúc mã nguồn & docs/IMPLEMENTATION_CONTRACT.md

INTERNAL PATHS (Backend → Dataset Manager):
- POST /api/v1/dataset-builds
- GET  /api/v1/dataset-builds/{id}
- POST /api/v1/dataset-builds/{id}/rebuild
- POST /api/v1/dataset-builds/{id}/deprecate
- POST /api/v1/dataset-builds/{id}/purge
- POST /api/v1/dataset-builds/{id}/registration-ack
- GET  /artifacts/v1/dataset-builds/{id}/manifest.json

INVARIANTS:
- Preserves both Idempotency-Key (header) and command_id (payload) on create/rebuild retries.
- Backend never calls purge directly on READY builds.
- Does not proxy shard downloads for workers.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DatasetManagerUnavailableError(Exception):
    """Raised when the Dataset Manager cannot be reached or returns a 5xx error."""

    pass


class DatasetManagerClient:
    """HTTP client for Management Backend → Dataset Manager communication."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout
        self._transport = transport
        if self._base_url:
            logger.info("DatasetManagerClient configured with base_url: %s", self._base_url)
        else:
            logger.warning("DatasetManagerClient running in unconfigured/stub mode.")

    @property
    def available(self) -> bool:
        return self._base_url is not None

    def create_build(
        self,
        *,
        dataset_build_id: str,
        command_id: str,
        idempotency_key: str,
        source: dict[str, Any],
        batch_size: int,
        partition_seed: int,
        profile: str,
        preprocessing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger build creation on Dataset Manager."""
        if not self.available:
            logger.warning(
                "Dataset Manager unavailable; build %s queued locally.", dataset_build_id
            )
            return {"status": "QUEUED_LOCAL", "dataset_build_id": dataset_build_id}

        url = f"{self._base_url}/api/v1/dataset-builds"
        headers = {"Idempotency-Key": idempotency_key}
        payload = {
            "command_id": command_id,
            "dataset_build_id": dataset_build_id,
            "source": source,
            "batch_size": batch_size,
            "partition_seed": partition_seed,
            "profile": profile,
            "preprocessing": preprocessing or {},
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.RequestError as exc:
            logger.error("Dataset Manager create_build failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def get_build(self, dataset_build_id: str) -> dict[str, Any] | None:
        """Fetch current build status from Dataset Manager."""
        if not self.available:
            return None

        url = f"{self._base_url}/api/v1/dataset-builds/{dataset_build_id}"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.get(url)
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
        except httpx.RequestError as exc:
            logger.error("Dataset Manager get_build failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def rebuild(
        self,
        *,
        source_dataset_build_id: str,
        new_dataset_build_id: str,
        command_id: str,
        idempotency_key: str,
        batch_size: int | None = None,
        partition_seed: int | None = None,
        preprocessing: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger rebuild from an existing build."""
        if not self.available:
            logger.warning(
                "Dataset Manager unavailable; rebuild %s queued locally.", new_dataset_build_id
            )
            return {"status": "QUEUED_LOCAL", "new_dataset_build_id": new_dataset_build_id}

        url = f"{self._base_url}/api/v1/dataset-builds/{source_dataset_build_id}/rebuild"
        headers = {"Idempotency-Key": idempotency_key}
        payload = {
            "command_id": command_id,
            "new_dataset_build_id": new_dataset_build_id,
            "batch_size": batch_size,
            "partition_seed": partition_seed,
            "preprocessing": preprocessing or {},
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except httpx.RequestError as exc:
            logger.error(
                "Dataset Manager rebuild failed for %s → %s: %s",
                source_dataset_build_id,
                new_dataset_build_id,
                exc,
            )
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def deprecate(self, dataset_build_id: str, reason: str | None = None) -> dict[str, Any]:
        """Mark build as DEPRECATED on Dataset Manager."""
        if not self.available:
            return {"status": "DEPRECATED_LOCAL", "dataset_build_id": dataset_build_id}

        url = f"{self._base_url}/api/v1/dataset-builds/{dataset_build_id}/deprecate"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json={"reason": reason})
                resp.raise_for_status()
                return resp.json()
        except httpx.RequestError as exc:
            logger.error("Dataset Manager deprecate failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def purge(self, dataset_build_id: str) -> dict[str, Any]:
        """Purge artifacts of a DEPRECATED or FAILED build from Dataset Manager storage."""
        if not self.available:
            return {"status": "PURGED_LOCAL", "dataset_build_id": dataset_build_id}

        url = f"{self._base_url}/api/v1/dataset-builds/{dataset_build_id}/purge"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json={})
                resp.raise_for_status()
                return resp.json()
        except httpx.RequestError as exc:
            logger.error("Dataset Manager purge failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def registration_ack(
        self, dataset_build_id: str, ack_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Acknowledge manifest persistence and transition to READY."""
        if not self.available:
            return {"status": "ACK_LOCAL", "dataset_build_id": dataset_build_id}

        url = f"{self._base_url}/api/v1/dataset-builds/{dataset_build_id}/registration-ack"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json=ack_payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.RequestError as exc:
            logger.error(
                "Dataset Manager registration-ack failed for %s: %s", dataset_build_id, exc
            )
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def get_manifest(self, dataset_build_id: str) -> tuple[dict[str, Any], bytes]:
        """Fetch published root dataset manifest and return (parsed_json, raw_bytes)."""
        if not self.available:
            raise DatasetManagerUnavailableError("Dataset Manager base URL is not configured.")

        url = f"{self._base_url}/artifacts/v1/dataset-builds/{dataset_build_id}/manifest.json"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.get(url)
                resp.raise_for_status()
                return resp.json(), resp.content
        except httpx.RequestError as exc:
            logger.error("Dataset Manager get_manifest failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc


_client: DatasetManagerClient | None = None


def get_client() -> DatasetManagerClient:
    global _client
    if _client is None:
        _client = DatasetManagerClient(base_url=None)
    return _client


def init_client(base_url: str | None) -> DatasetManagerClient:
    global _client
    _client = DatasetManagerClient(base_url=base_url)
    return _client
