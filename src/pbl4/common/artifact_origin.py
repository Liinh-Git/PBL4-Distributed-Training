"""Validation and safe URL resolution for immutable dataset artifacts."""

from __future__ import annotations

import posixpath
from urllib.parse import unquote, urlsplit, urlunsplit


def _validated_http_url(value: str, *, name: str) -> tuple[str, str, str]:
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{name} must be an absolute HTTP(S) artifact URL")
    decoded_path = unquote(parsed.path)
    segments = decoded_path.split("/")
    if any(segment in {".", ".."} for segment in segments):
        raise ValueError(f"{name} contains unsafe path traversal")
    normalized = posixpath.normpath(decoded_path)
    if not normalized.startswith("/"):
        raise ValueError(f"{name} path is not absolute")
    return parsed.scheme.lower(), parsed.netloc.lower(), normalized


def derive_root_manifest_path(artifact_base_url: str, manifest_uri: str) -> str:
    """Return a safe relative manifest path within one authoritative origin."""
    base_scheme, base_netloc, base_path = _validated_http_url(
        artifact_base_url.rstrip("/"), name="artifact_base_url"
    )
    manifest_scheme, manifest_netloc, manifest_path = _validated_http_url(
        manifest_uri, name="manifest_uri"
    )
    if (base_scheme, base_netloc) != (manifest_scheme, manifest_netloc):
        raise ValueError("manifest_uri is outside artifact_base_url origin")
    prefix = base_path.rstrip("/") + "/"
    if not manifest_path.startswith(prefix):
        raise ValueError("manifest_uri escapes artifact_base_url path")
    relative = manifest_path[len(prefix) :]
    if not relative or relative.startswith("/"):
        raise ValueError("manifest_uri does not identify a root manifest")
    return relative


def resolve_artifact_url(artifact_base_url: str, relative_path: str) -> str:
    """Resolve an artifact-relative path without permitting origin/path escape."""
    scheme, netloc, base_path = _validated_http_url(
        artifact_base_url.rstrip("/"), name="artifact_base_url"
    )
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("Artifact relative path must be non-empty")
    decoded = unquote(relative_path.replace("\\", "/"))
    if decoded.startswith("/") or any(part in {".", ".."} for part in decoded.split("/")):
        raise ValueError("Artifact relative path escapes its origin")
    resolved_path = posixpath.normpath(base_path.rstrip("/") + "/" + decoded)
    prefix = base_path.rstrip("/") + "/"
    if not resolved_path.startswith(prefix):
        raise ValueError("Artifact relative path escapes its origin")
    return urlunsplit((scheme, netloc, resolved_path, "", ""))
