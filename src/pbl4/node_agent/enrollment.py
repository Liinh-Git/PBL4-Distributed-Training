"""One-time enrollment client for Node Agent.

Contacts Management Backend at POST /api/v1/nodes/enroll using an operator-provided
one-time enrollment code to obtain the persistent NodeIdentity (node_id and node_secret).
Guarantees:
- Enrollment code is never persisted to disk.
- Node secret is never logged in plaintext.
- Never re-enrolls if identity already exists.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from pbl4.node_agent.identity import NodeIdentity

logger = logging.getLogger(__name__)


def enroll(
    backend_url: str,
    enrollment_code: str,
    static_capabilities: dict[str, Any] | None = None,
    *,
    timeout: float = 10.0,
) -> NodeIdentity:
    """Enroll this host with the Management Backend to obtain a permanent NodeIdentity.

    Args:
        backend_url: Base URL of the Management Backend (e.g. 'http://127.0.0.1:8000').
        enrollment_code: One-time token provided by the operator.
        static_capabilities: Optional hardware/system capabilities discovered locally.
        timeout: HTTP request timeout in seconds.

    Returns:
        NodeIdentity containing the assigned node_id and generated node_secret.

    Raises:
        ValueError: On invalid arguments or response structure.
        RuntimeError: On HTTP error or connection failure.
    """
    if not isinstance(backend_url, str) or not backend_url.strip():
        raise ValueError("backend_url must be a non-empty string")
    if not isinstance(enrollment_code, str) or not enrollment_code.strip():
        raise ValueError("enrollment_code must be a non-empty string")

    endpoint = f"{backend_url.rstrip('/')}/api/v1/nodes/enroll"
    payload = {
        "enrollment_code": enrollment_code,
        "capabilities": static_capabilities or {},
    }
    body_bytes = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        endpoint,
        data=body_bytes,
        headers={
            "Authorization": f"Bearer {enrollment_code}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    logger.info("Attempting Node enrollment with backend at %s", endpoint)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        err_msg = f"Enrollment HTTP request failed with status {exc.code}"
        logger.error("%s", err_msg)
        raise RuntimeError(err_msg) from exc
    except urllib.error.URLError as exc:
        err_msg = f"Failed to connect to backend for enrollment: {exc.reason}"
        logger.error("%s", err_msg)
        raise RuntimeError(err_msg) from exc
    except Exception as exc:
        logger.error("Unexpected error during node enrollment: %s", exc)
        raise RuntimeError(f"Unexpected enrollment error: {exc}") from exc

    if status_code not in (200, 201):
        raise RuntimeError(f"Unexpected status code {status_code} during node enrollment")

    try:
        data = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid JSON response from enrollment endpoint") from exc

    # Support both direct payload {"node_id": ..., "node_secret": ...}
    # and standard API envelope {"data": {"node_id": ..., "node_secret": ...}}
    if isinstance(data, dict) and "data" in data and isinstance(data["data"], dict):
        creds = data["data"]
    elif isinstance(data, dict):
        creds = data
    else:
        raise ValueError("Invalid response structure from enrollment endpoint")

    node_id = creds.get("node_id")
    node_secret = creds.get("node_secret")

    if not isinstance(node_id, str) or not node_id.strip():
        raise ValueError("Enrollment response missing valid 'node_id'")
    if not isinstance(node_secret, str) or not node_secret.strip():
        raise ValueError("Enrollment response missing valid 'node_secret'")

    logger.info("Successfully enrolled node with node_id=%s", node_id)
    return NodeIdentity(node_id=node_id, node_secret=node_secret)
