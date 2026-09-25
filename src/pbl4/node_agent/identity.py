"""Local persistent identity storage for Node Agent.

Manages persisting and loading the Node's credential pair (node_id and node_secret).
Guarantees:
- Node secret is redacted in string representations and never logged.
- POSIX permissions 0600 on the identity file when supported.
- Agent restart re-uses the established Node identity without re-enrolling.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class NodeIdentity:
    """Credential pair identifying a registered Node on the Management Backend."""

    node_id: str
    node_secret: str

    def __post_init__(self) -> None:
        if not isinstance(self.node_id, str) or not self.node_id.strip():
            raise ValueError("node_id must be a non-empty string")
        if not isinstance(self.node_secret, str) or not self.node_secret.strip():
            raise ValueError("node_secret must be a non-empty string")

    def __repr__(self) -> str:
        return f"NodeIdentity(node_id={self.node_id!r}, node_secret='***REDACTED***')"

    def to_dict(self) -> dict[str, str]:
        return {"node_id": self.node_id, "node_secret": self.node_secret}

    @classmethod
    def from_dict(cls, data: object) -> NodeIdentity:
        if not isinstance(data, dict):
            raise ValueError("Node identity data must be a JSON object")
        node_id = data.get("node_id")
        node_secret = data.get("node_secret")
        if not isinstance(node_id, str) or not node_id.strip():
            raise ValueError("Malformed node_identity: missing or invalid node_id")
        if not isinstance(node_secret, str) or not node_secret.strip():
            raise ValueError("Malformed node_identity: missing or invalid node_secret")
        return cls(node_id=node_id, node_secret=node_secret)


def identity_path(var_dir: str | Path) -> Path:
    """Return the filesystem path for the persisted node identity file."""
    return Path(var_dir) / "node_identity.json"


def save_identity(var_dir: str | Path, identity: NodeIdentity) -> Path:
    """Persist node identity to local storage with restrictive permissions."""
    target_dir = Path(var_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(target_dir, 0o700)
        except OSError:
            pass

    path = identity_path(target_dir)
    content = json.dumps(identity.to_dict(), indent=2) + "\n"
    path.write_text(content, encoding="utf-8")

    if os.name != "nt":
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    return path


def load_identity(var_dir: str | Path) -> NodeIdentity | None:
    """Load existing node identity from storage.

    Returns None if identity file does not exist.
    Raises ValueError if identity file is corrupt or invalid.
    """
    path = identity_path(var_dir)
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Malformed node identity JSON at {path}: {exc}") from exc

    return NodeIdentity.from_dict(data)
