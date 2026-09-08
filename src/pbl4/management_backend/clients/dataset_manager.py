"""Dataset Manager client — Management Backend HTTP client to Dataset Manager.

V1 status: stub — external Dataset Manager not yet available.
The boundary and interface are defined; actual HTTP calls are deferred.

CRITICAL V1 INVARIANTS:
- Backend never self-infers dataset READY status; that determination belongs to Dataset Manager.
- Does NOT proxy shard artifact downloads for workers.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class DatasetManagerClient:
    """HTTP client for Management Backend → Dataset Manager communication.

    V1 status: stub — returns unavailable/unknown for all queries.
    Replace the method bodies with actual httpx calls when Dataset Manager is deployed.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = base_url
        if base_url:
            logger.info("DatasetManagerClient configured: %s", base_url)
        else:
            logger.warning("DatasetManagerClient: no base_url configured; running in stub mode.")

    @property
    def available(self) -> bool:
        return self._base_url is not None

    def trigger_build(self, dataset_build_id: str, payload: dict) -> dict:
        """Trigger a new dataset build on the Dataset Manager.

        Returns the Dataset Manager's acknowledgement payload.
        Raises DatasetManagerUnavailableError if not reachable.
        """
        if not self.available:
            logger.warning(
                "Dataset Manager unavailable; build trigger skipped for %s.", dataset_build_id
            )
            return {"status": "QUEUED_LOCAL", "note": "Dataset Manager not configured."}
        # TODO: implement httpx POST when Dataset Manager is deployed
        raise NotImplementedError("Dataset Manager HTTP integration not yet implemented.")

    def get_build_status(self, dataset_build_id: str) -> dict | None:
        """Query build progress from Dataset Manager. Returns None if unavailable."""
        if not self.available:
            return None
        # TODO: implement httpx GET when Dataset Manager is deployed
        raise NotImplementedError("Dataset Manager HTTP integration not yet implemented.")

    def delete_build(self, dataset_build_id: str) -> bool:
        """Request deletion of a build. Returns True if accepted."""
        if not self.available:
            logger.warning("Dataset Manager unavailable; delete skipped for %s.", dataset_build_id)
            return False
        raise NotImplementedError("Dataset Manager HTTP integration not yet implemented.")


class DatasetManagerUnavailableError(Exception):
    """Raised when the Dataset Manager cannot be reached."""


# Module-level singleton; initialized by app startup
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
