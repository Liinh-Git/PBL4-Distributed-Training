"""Dataset Manager configuration.

Canonical responsibility:
- Holds deployment configuration (host, port, storage directory, logging) for Dataset Manager.

Important boundary:
- Does NOT configure Runtime training parameters, worker topology, or synchronization policies.

Status:
- Scaffold only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DatasetManagerConfig:
    """Configuration for the Dataset Manager process."""

    host: str = "127.0.0.1"
    port: int | None = None
    store_dir: str = ""
    log_level: str = "INFO"
