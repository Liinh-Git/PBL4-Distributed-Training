"""Configuration for PBL4 Node Agent.

Enforces constraints from NODE_AGENT_IMPLEMENTATION_PLAN.md:
- No persistent storage of one-time enrollment codes.
- Only non-secret connection and polling parameters.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NodeAgentConfig:
    """Immutable runtime configuration for the Node Agent process."""

    backend_url: str
    var_dir: str = "var/agent"
    heartbeat_interval_seconds: float = 5.0
    telemetry_interval_seconds: float = 10.0
    reconnect_min_seconds: float = 1.0
    reconnect_max_seconds: float = 30.0
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not isinstance(self.backend_url, str) or not self.backend_url.strip():
            raise ValueError("backend_url must be a non-empty string")
        if not isinstance(self.var_dir, str) or not self.var_dir.strip():
            raise ValueError("var_dir must be a non-empty string")
        if (
            not isinstance(self.heartbeat_interval_seconds, (int, float))
            or self.heartbeat_interval_seconds <= 0
        ):
            raise ValueError("heartbeat_interval_seconds must be a positive number")
        if (
            not isinstance(self.telemetry_interval_seconds, (int, float))
            or self.telemetry_interval_seconds <= 0
        ):
            raise ValueError("telemetry_interval_seconds must be a positive number")
        if (
            not isinstance(self.reconnect_min_seconds, (int, float))
            or self.reconnect_min_seconds <= 0
        ):
            raise ValueError("reconnect_min_seconds must be a positive number")
        if (
            not isinstance(self.reconnect_max_seconds, (int, float))
            or self.reconnect_max_seconds < self.reconnect_min_seconds
        ):
            raise ValueError("reconnect_max_seconds must be >= reconnect_min_seconds")
        if self.log_level.upper() not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"Invalid log_level: {self.log_level}")

    @classmethod
    def from_env(cls, **overrides: object) -> NodeAgentConfig:
        """Create NodeAgentConfig reading default values from environment variables."""
        backend_url = overrides.get("backend_url") or os.getenv(
            "PBL4_BACKEND_URL", "http://127.0.0.1:8000"
        )
        var_dir = overrides.get("var_dir") or os.getenv("PBL4_VAR_DIR", "var/agent")
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
        log_level = overrides.get("log_level") or os.getenv("PBL4_LOG_LEVEL", "INFO")

        return cls(
            backend_url=str(backend_url),
            var_dir=str(var_dir),
            heartbeat_interval_seconds=float(heartbeat_interval),
            telemetry_interval_seconds=float(telemetry_interval),
            reconnect_min_seconds=float(reconnect_min),
            reconnect_max_seconds=float(reconnect_max),
            log_level=str(log_level),
        )
