"""Management Backend configuration.

Canonical responsibility:
- Holds deployment configuration for the Management Backend process.
- Loads settings from environment variables or explicit configuration files.

Important boundary:
- database_url must be provided via DATABASE_URL; no default database is assumed.
- Does NOT define Runtime training strategy, worker count, or synchronization parameters.

Status:
- Scaffold only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BackendConfig:
    """Configuration for the Backend process.

    Values should be supplied via environment variables or explicit deployment configs.
    No production credentials or concrete database URLs are hardcoded as defaults.
    """

    host: str = "127.0.0.1"
    port: int | None = None
    database_url: str | None = None  # Configured via DATABASE_URL
    runtime_host: str = "127.0.0.1"
    runtime_management_port: int | None = None
    dataset_manager_host: str = "127.0.0.1"
    dataset_manager_port: int | None = None
    log_level: str = "INFO"
