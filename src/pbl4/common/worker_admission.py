"""Worker admission token issuance and verification.

Reference: NODE_AGENT_IMPLEMENTATION_PLAN.md & NODE_AGENT_DESIGN.md
Module provides pure stdlib HMAC-SHA256 signed short-lived join tokens.
Used across Backend (issue) and Runtime (verify) without sharing domain models.
"""

from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
import hashlib
import hmac
import json
import secrets
import time
from typing import Any

from pbl4.common.errors import PBL4Error


class WorkerAdmissionError(PBL4Error):
    """Exception raised when worker join token issuance or validation fails."""


@dataclass(frozen=True, slots=True)
class WorkerAdmissionClaims:
    """Validated claims decoded from a canonical worker join token."""

    v: int
    attempt_id: str
    allocation_id: str
    node_id: str
    exp: int
    nonce: str


def _b64url_encode(data: bytes) -> str:
    """Encode bytes to URL-safe base64 without '=' padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    """Decode URL-safe base64 string, adding missing '=' padding if necessary."""
    pad_len = (-len(s)) % 4
    padded = s + ("=" * pad_len)
    return base64.urlsafe_b64decode(padded)


def issue_worker_join_token(
    secret: str,
    attempt_id: str,
    allocation_id: str,
    node_id: str,
    *,
    ttl_seconds: int = 600,
    now: float | None = None,
) -> str:
    """Issue a canonical HMAC-SHA256 signed short-lived worker join token.

    Format: <payload_b64>.<signature_b64>
    """
    if not isinstance(secret, str) or not secret:
        raise WorkerAdmissionError("Admission secret must be a non-empty string")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise WorkerAdmissionError("attempt_id must be a non-empty string")
    if not isinstance(allocation_id, str) or not allocation_id:
        raise WorkerAdmissionError("allocation_id must be a non-empty string")
    if not isinstance(node_id, str) or not node_id:
        raise WorkerAdmissionError("node_id must be a non-empty string")
    if not isinstance(ttl_seconds, (int, float)) or ttl_seconds <= 0:
        raise WorkerAdmissionError("ttl_seconds must be a positive integer")

    current_time = time.time() if now is None else float(now)
    exp = int(current_time + ttl_seconds)
    nonce = secrets.token_hex(16)

    payload: dict[str, Any] = {
        "v": 1,
        "attempt_id": attempt_id,
        "allocation_id": allocation_id,
        "node_id": node_id,
        "exp": exp,
        "nonce": nonce,
    }

    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)

    signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)

    return f"{payload_b64}.{signature_b64}"


def verify_worker_join_token(
    secret: str,
    token: str,
    expected_attempt_id: str,
    expected_allocation_id: str,
    expected_node_id: str,
    *,
    now: float | None = None,
) -> WorkerAdmissionClaims:
    """Verify signature, expiry, and claim matching of a worker join token.

    Returns WorkerAdmissionClaims on success.
    Raises WorkerAdmissionError on any verification failure without leaking secret.
    """
    if not isinstance(secret, str) or not secret:
        raise WorkerAdmissionError("Admission secret must be a non-empty string")
    if not isinstance(token, str) or not token:
        raise WorkerAdmissionError("Worker join token must be a non-empty string")

    parts = token.split(".")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise WorkerAdmissionError("Malformed worker join token: expected two non-empty dot-separated parts")

    payload_b64, signature_b64 = parts

    try:
        payload_bytes = _b64url_decode(payload_b64)
    except (binascii.Error, ValueError) as exc:
        raise WorkerAdmissionError("Malformed Base64 payload in worker join token") from exc

    try:
        actual_signature = _b64url_decode(signature_b64)
    except (binascii.Error, ValueError) as exc:
        raise WorkerAdmissionError("Malformed Base64 signature in worker join token") from exc

    expected_signature = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(actual_signature, expected_signature):
        raise WorkerAdmissionError("Invalid token signature")

    try:
        payload_obj = json.loads(payload_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerAdmissionError("Malformed JSON in worker join token payload") from exc

    if not isinstance(payload_obj, dict):
        raise WorkerAdmissionError("Token payload must be a JSON object")

    required_keys = {"v", "attempt_id", "allocation_id", "node_id", "exp", "nonce"}
    if not required_keys.issubset(payload_obj.keys()):
        missing = sorted(required_keys - set(payload_obj.keys()))
        raise WorkerAdmissionError(f"Missing required claim(s) in token: {', '.join(missing)}")

    version = payload_obj["v"]
    if not isinstance(version, int) or isinstance(version, bool) or version != 1:
        raise WorkerAdmissionError(f"Unsupported token version: {version}")

    attempt_id = payload_obj["attempt_id"]
    allocation_id = payload_obj["allocation_id"]
    node_id = payload_obj["node_id"]
    exp = payload_obj["exp"]
    nonce = payload_obj["nonce"]

    if not isinstance(attempt_id, str) or not attempt_id:
        raise WorkerAdmissionError("attempt_id claim must be a non-empty string")
    if not isinstance(allocation_id, str) or not allocation_id:
        raise WorkerAdmissionError("allocation_id claim must be a non-empty string")
    if not isinstance(node_id, str) or not node_id:
        raise WorkerAdmissionError("node_id claim must be a non-empty string")
    if not isinstance(nonce, str) or not nonce:
        raise WorkerAdmissionError("nonce claim must be a non-empty string")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        raise WorkerAdmissionError("exp claim must be a numeric timestamp")

    current_time = time.time() if now is None else float(now)
    if exp < current_time:
        raise WorkerAdmissionError(f"Worker join token has expired (exp={int(exp)}, now={int(current_time)})")

    if attempt_id != expected_attempt_id:
        raise WorkerAdmissionError(
            f"Token attempt_id scope mismatch (claim '{attempt_id}' != expected '{expected_attempt_id}')"
        )
    if allocation_id != expected_allocation_id:
        raise WorkerAdmissionError(
            f"Token allocation_id scope mismatch (claim '{allocation_id}' != expected '{expected_allocation_id}')"
        )
    if node_id != expected_node_id:
        raise WorkerAdmissionError(
            f"Token node_id scope mismatch (claim '{node_id}' != expected '{expected_node_id}')"
        )

    return WorkerAdmissionClaims(
        v=version,
        attempt_id=attempt_id,
        allocation_id=allocation_id,
        node_id=node_id,
        exp=int(exp),
        nonce=nonce,
    )
