"""Configuration for PBL4 Node Agent.

Enforces constraints from NODE_AGENT_IMPLEMENTATION_PLAN.md:
- Only non-secret connection and polling parameters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NodeAgentConfig:
    """Immutable runtime configuration for the Node Agent process."""

    backend_url: str
    var_dir: str = "var/demo-node-0"
    heartbeat_interval_seconds: float = 5.0
    telemetry_interval_seconds: float = 10.0
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    max_worker_crash_retries: int = 3
    crash_retry_delay_seconds: float = 2.0
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not isinstance(self.backend_url, str) or not self.backend_url.strip():
            raise ValueError("backend_url must be a non-empty string")
        if not isinstance(self.var_dir, str) or not self.var_dir.strip():
            raise ValueError("var_dir must be a non-empty string")
        if (
            isinstance(self.heartbeat_interval_seconds, bool)
            or not isinstance(self.heartbeat_interval_seconds, (int, float))
            or self.heartbeat_interval_seconds <= 0
        ):
            raise ValueError("heartbeat_interval_seconds must be a positive number")
        if (
            isinstance(self.telemetry_interval_seconds, bool)
            or not isinstance(self.telemetry_interval_seconds, (int, float))
            or self.telemetry_interval_seconds <= 0
        ):
            raise ValueError("telemetry_interval_seconds must be a positive number")
        if (
            isinstance(self.reconnect_min_seconds, bool)
            or not isinstance(self.reconnect_min_seconds, (int, float))
            or self.reconnect_min_seconds <= 0
        ):
            raise ValueError("reconnect_min_seconds must be a positive number")
        if (
            isinstance(self.reconnect_max_seconds, bool)
            or not isinstance(self.reconnect_max_seconds, (int, float))
            or self.reconnect_max_seconds < self.reconnect_min_seconds
        ):
            raise ValueError("reconnect_max_seconds must be >= reconnect_min_seconds")
        if (
            isinstance(self.max_worker_crash_retries, bool)
            or not isinstance(self.max_worker_crash_retries, int)
            or self.max_worker_crash_retries < 0
        ):
            raise ValueError("max_worker_crash_retries must be a non-negative integer")
        if (
            isinstance(self.crash_retry_delay_seconds, bool)
            or not isinstance(self.crash_retry_delay_seconds, (int, float))
            or self.crash_retry_delay_seconds < 0
        ):
            raise ValueError("crash_retry_delay_seconds must be a non-negative number")
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid log_level: {self.log_level}")

    @classmethod
    def from_env(cls, **overrides: object) -> NodeAgentConfig:
        """Create NodeAgentConfig reading default values from environment variables."""
        backend_url = overrides.get("backend_url") or os.getenv(
            "PBL4_BACKEND_URL", "http://127.0.0.1:8000"
        )
        var_dir = overrides.get("var_dir") or os.getenv("PBL4_VAR_DIR", "var/demo-node-0")
        heartbeat_interval = overrides.get("heartbeat_interval_seconds") or float(
            os.getenv("PBL4_HEARTBEAT_INTERVAL_SECONDS", "5.0")
        )
        telemetry_interval = overrides.get("telemetry_interval_seconds") or float(
            os.getenv("PBL4_TELEMETRY_INTERVAL_SECONDS", "10.0")
        )
        reconnect_min = overrides.get("reconnect_min_seconds") or float(
            os.getenv("PBL4_RECONNECT_MIN_SECONDS", "1.0")
        )
        reconnect_max = overrides.get("reconnect_max_seconds") or float(
            os.getenv("PBL4_RECONNECT_MAX_SECONDS", "30.0")
        )
        max_retries_raw = overrides.get("max_worker_crash_retries")
        retry_delay_raw = overrides.get("crash_retry_delay_seconds")
        if isinstance(max_retries_raw, bool) or (
            max_retries_raw is not None and not isinstance(max_retries_raw, int)
        ):
            raise ValueError("max_worker_crash_retries must be a non-negative integer")
        if isinstance(retry_delay_raw, bool) or (
            retry_delay_raw is not None and not isinstance(retry_delay_raw, (int, float))
        ):
            raise ValueError("crash_retry_delay_seconds must be a non-negative number")
        log_level = overrides.get("log_level") or os.getenv("PBL4_LOG_LEVEL", "INFO")

        return cls(
            backend_url=str(backend_url),
            var_dir=str(var_dir),
            heartbeat_interval_seconds=float(heartbeat_interval),
            telemetry_interval_seconds=float(telemetry_interval),
            reconnect_min_seconds=float(reconnect_min),
            reconnect_max_seconds=float(reconnect_max),
            max_worker_crash_retries=(
                3 if max_retries_raw is None else max_retries_raw
            ),
            crash_retry_delay_seconds=(
                2.0 if retry_delay_raw is None else float(retry_delay_raw)
            ),
            log_level=str(log_level),
        )
