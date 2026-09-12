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
- Backend NEVER generates or sends dataset_build_id on create or rebuild.
- When unavailable, Backend raises DatasetManagerUnavailableError truthfully and never
  fabricates a local success state.
- Purge payload carries exact canonical fields: command_id, reason, force=false.
- Registration ACK carries: dataset_manifest_hash, registration_id, catalog_persisted_at.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class DatasetManagerUnavailableError(Exception):
    """Raised when Dataset Manager cannot be reached, returns a 5xx error, or is unconfigured."""

    pass


class DatasetManagerBusinessError(Exception):
    """Raised when Dataset Manager responds with an HTTP 4xx business rejection."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(f"Dataset Manager business rejection {status_code} [{code}]: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.retryable = retryable


class DatasetManagerProtocolError(DatasetManagerUnavailableError):
    """Raised when a control response violates the canonical DM envelope."""


def _unwrap_control_response(resp: httpx.Response) -> dict[str, Any]:
    """Return ``data`` from the canonical ``request_id/data/error`` envelope."""
    try:
        body = resp.json()
    except Exception as exc:
        raise DatasetManagerProtocolError(
            "Dataset Manager returned a non-JSON control response."
        ) from exc

    if not isinstance(body, dict) or set(body) != {"request_id", "data", "error"}:
        raise DatasetManagerProtocolError(
            "Dataset Manager control response does not match the canonical envelope."
        )
    if not isinstance(body["request_id"], str) or not body["request_id"]:
        raise DatasetManagerProtocolError("Dataset Manager response has an invalid request_id.")

    error = body["error"]
    if error is not None:
        if not isinstance(error, dict):
            raise DatasetManagerProtocolError("Dataset Manager response has an invalid error.")
        raise DatasetManagerBusinessError(
            status_code=resp.status_code,
            code=error.get("code") or "DATASET_MANAGER_ERROR",
            message=error.get("message") or "Dataset Manager rejected the request.",
            details=error.get("details"),
            retryable=bool(error.get("retryable", False)),
        )

    data = body["data"]
    if not isinstance(data, dict):
        raise DatasetManagerProtocolError(
            "Dataset Manager success response data must be an object."
        )
    return data


def _handle_response(resp: httpx.Response) -> httpx.Response:
    """Validate response status, separating 4xx business rejections from 5xx/network errors."""
    if resp.status_code < 400:
        return resp
    if resp.status_code >= 500:
        raise DatasetManagerUnavailableError(
            f"Dataset Manager returned server error {resp.status_code}"
        )

    # 4xx: Parse downstream business rejection
    code = "DATASET_MANAGER_ERROR"
    message = f"Dataset Manager rejected request with HTTP {resp.status_code}"
    details = None
    retryable = False

    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error", body)
            if isinstance(err, dict):
                code = err.get("code") or code
                message = err.get("message") or message
                details = err.get("details")
                retryable = bool(err.get("retryable", False))
            elif isinstance(body.get("code"), str):
                code = body["code"]
                message = body.get("message") or message
                details = body.get("details")
                retryable = bool(body.get("retryable", False))
    except Exception:
        message = (
            f"Dataset Manager rejected request with HTTP {resp.status_code} "
            "(malformed error response)"
        )

    raise DatasetManagerBusinessError(
        status_code=resp.status_code,
        code=code,
        message=message,
        details=details,
        retryable=retryable,
    )


class DatasetManagerClient:
    """HTTP client for Management Backend → Dataset Manager communication."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/") if base_url else None
        self._timeout = timeout
        self._transport = transport
        if self._base_url:
            logger.info("DatasetManagerClient configured with base_url: %s", self._base_url)
        else:
            logger.info("DatasetManagerClient running in unconfigured mode.")

    @property
    def available(self) -> bool:
        return self._base_url is not None

    def check_health(self) -> str:
        """Check Dataset Manager reachability truthfully."""
        if not self.available or not self._base_url:
            return "unknown"
        try:
            with httpx.Client(timeout=1.0, transport=self._transport) as client:
                resp = client.get(f"{self._base_url}/healthz")
                if resp.status_code == httpx.codes.OK:
                    return "healthy"
                return "degraded"
        except httpx.HTTPError:
            return "unreachable"

    def create_build(
        self,
        *,
        command_id: str,
        idempotency_key: str,
        source: dict[str, Any],
        profile: str,
        input_shape: list[int],
        normalization: dict[str, Any],
        batch_size: int,
        partition_seed: int,
        shard_count: int = 3,
    ) -> dict[str, Any]:
        """Trigger build creation on Dataset Manager.

        Backend resolves public request into canonical internal DM body.
        Backend does NOT generate or send dataset_build_id.
        """
        if not self.available:
            raise DatasetManagerUnavailableError("Dataset Manager base URL is not configured.")

        url = f"{self._base_url}/api/v1/dataset-builds"
        headers = {"Idempotency-Key": idempotency_key}
        payload = {
            "source": source,
            "profile": profile,
            "input_shape": input_shape,
            "normalization": normalization,
            "batch_size": batch_size,
            "shard_count": shard_count,
            "partition_seed": partition_seed,
            "command_id": command_id,
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json=payload, headers=headers)
                _handle_response(resp)
                return _unwrap_control_response(resp)
        except DatasetManagerBusinessError:
            raise
        except DatasetManagerUnavailableError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.error("Dataset Manager create_build transport failed: %s", exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc
        except Exception as exc:
            logger.error("Dataset Manager create_build failed: %s", exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def get_build(self, dataset_build_id: str) -> dict[str, Any] | None:
        """Fetch current build status from Dataset Manager."""
        if not self.available:
            raise DatasetManagerUnavailableError("Dataset Manager base URL is not configured.")

        url = f"{self._base_url}/api/v1/dataset-builds/{dataset_build_id}"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.get(url)
                if resp.status_code == 404:
                    return None
                _handle_response(resp)
                return _unwrap_control_response(resp)
        except DatasetManagerBusinessError:
            raise
        except DatasetManagerUnavailableError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.error(
                "Dataset Manager get_build transport failed for %s: %s", dataset_build_id, exc
            )
            raise DatasetManagerUnavailableError(str(exc)) from exc
        except Exception as exc:
            logger.error("Dataset Manager get_build failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def rebuild(
        self,
        *,
        source_dataset_build_id: str,
        command_id: str,
        idempotency_key: str,
        batch_size: int | None = None,
        partition_seed: int | None = None,
        input_shape: list[int] | None = None,
        normalization: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Trigger rebuild from an existing build on Dataset Manager.

        Dataset Manager generates the new build ID.
        """
        if not self.available:
            raise DatasetManagerUnavailableError("Dataset Manager base URL is not configured.")

        url = f"{self._base_url}/api/v1/dataset-builds/{source_dataset_build_id}/rebuild"
        headers = {"Idempotency-Key": idempotency_key}
        payload: dict[str, Any] = {
            "command_id": command_id,
        }
        if batch_size is not None:
            payload["batch_size"] = batch_size
        if partition_seed is not None:
            payload["partition_seed"] = partition_seed
        if input_shape is not None:
            payload["input_shape"] = input_shape
        if normalization is not None:
            payload["normalization"] = normalization

        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json=payload, headers=headers)
                _handle_response(resp)
                return _unwrap_control_response(resp)
        except DatasetManagerBusinessError:
            raise
        except DatasetManagerUnavailableError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.error(
                "Dataset Manager rebuild transport failed for %s: %s",
                source_dataset_build_id,
                exc,
            )
            raise DatasetManagerUnavailableError(str(exc)) from exc
        except Exception as exc:
            logger.error(
                "Dataset Manager rebuild failed for %s: %s",
                source_dataset_build_id,
                exc,
            )
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def deprecate(self, dataset_build_id: str, reason: str | None = None) -> dict[str, Any]:
        """Mark build as DEPRECATED on Dataset Manager."""
        if not self.available:
            raise DatasetManagerUnavailableError("Dataset Manager base URL is not configured.")

        url = f"{self._base_url}/api/v1/dataset-builds/{dataset_build_id}/deprecate"
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json={"reason": reason})
                _handle_response(resp)
                return _unwrap_control_response(resp)
        except DatasetManagerBusinessError:
            raise
        except DatasetManagerUnavailableError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.error(
                "Dataset Manager deprecate transport failed for %s: %s", dataset_build_id, exc
            )
            raise DatasetManagerUnavailableError(str(exc)) from exc
        except Exception as exc:
            logger.error("Dataset Manager deprecate failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def purge(
        self,
        dataset_build_id: str,
        *,
        command_id: str,
        reason: str | None = None,
        force: bool = False,
    ) -> dict[str, Any]:
        """Purge artifacts of a DEPRECATED or FAILED build from Dataset Manager storage."""
        if not self.available:
            raise DatasetManagerUnavailableError("Dataset Manager base URL is not configured.")

        url = f"{self._base_url}/api/v1/dataset-builds/{dataset_build_id}/purge"
        payload = {
            "command_id": command_id,
            "reason": reason or "Operator requested purge",
            "force": force,
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json=payload)
                _handle_response(resp)
                return _unwrap_control_response(resp)
        except DatasetManagerBusinessError:
            raise
        except DatasetManagerUnavailableError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.error("Dataset Manager purge transport failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc
        except Exception as exc:
            logger.error("Dataset Manager purge failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc

    def registration_ack(
        self,
        dataset_build_id: str,
        *,
        dataset_manifest_hash: str,
        registration_id: str,
        catalog_persisted_at: str,
    ) -> dict[str, Any]:
        """Acknowledge manifest persistence and transition to READY on Dataset Manager."""
        if not self.available:
            raise DatasetManagerUnavailableError("Dataset Manager base URL is not configured.")

        url = f"{self._base_url}/api/v1/dataset-builds/{dataset_build_id}/registration-ack"
        payload = {
            "dataset_manifest_hash": dataset_manifest_hash,
            "registration_id": registration_id,
            "catalog_persisted_at": catalog_persisted_at,
        }
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                resp = client.post(url, json=payload)
                _handle_response(resp)
                return _unwrap_control_response(resp)
        except DatasetManagerBusinessError:
            raise
        except DatasetManagerUnavailableError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.error(
                "Dataset Manager registration-ack transport failed for %s: %s",
                dataset_build_id,
                exc,
            )
            raise DatasetManagerUnavailableError(str(exc)) from exc
        except Exception as exc:
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
                _handle_response(resp)
                return resp.json(), resp.content
        except DatasetManagerBusinessError:
            raise
        except DatasetManagerUnavailableError:
            raise
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            logger.error(
                "Dataset Manager get_manifest transport failed for %s: %s", dataset_build_id, exc
            )
            raise DatasetManagerUnavailableError(str(exc)) from exc
        except Exception as exc:
            logger.error("Dataset Manager get_manifest failed for %s: %s", dataset_build_id, exc)
            raise DatasetManagerUnavailableError(str(exc)) from exc


_client: DatasetManagerClient | None = None


def get_client() -> DatasetManagerClient:
    global _client
    if _client is None:
        _client = DatasetManagerClient(base_url=None)
    return _client


def init_client(
    base_url: str | None,
    timeout: float = 30.0,
    transport: httpx.BaseTransport | None = None,
) -> DatasetManagerClient:
    global _client
    _client = DatasetManagerClient(base_url=base_url, timeout=timeout, transport=transport)
    return _client
