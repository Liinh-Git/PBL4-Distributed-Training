"""Authenticated HTTP client for Runtime checkpoint inventory, export and cleanup."""

from __future__ import annotations

from contextlib import contextmanager

import httpx


class RuntimeArtifacts:
    def __init__(self, base_url: str, token: str):
        if not base_url or not token:
            raise ValueError("Runtime artifact URL and token must be configured")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            timeout=httpx.Timeout(120, connect=5),
            trust_env=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._http.close()

    def inventory(self):
        cursor = ""
        while True:
            response = self._http.get("/inventory", params={"after": cursor, "limit": 100})
            response.raise_for_status()
            page = response.json()
            yield from page["items"]
            following = page["next_cursor"]
            if following is None:
                return
            if not isinstance(following, str) or following <= cursor:
                raise ValueError("Non-progressing artifact inventory cursor")
            cursor = following

    def purge(self, descriptor: dict):
        response = self._http.post("/purge", json={"descriptor": descriptor})
        response.raise_for_status()

    @contextmanager
    def export(self, descriptor: dict, contract: dict):
        with self._http.stream(
            "POST", "/export", json={"descriptor": descriptor, "contract": contract}
        ) as response:
            response.raise_for_status()
            if response.headers.get("Content-Type") != "application/zip":
                raise ValueError("Invalid artifact response type")
            length = int(response.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("Invalid artifact response length")
            yield response
