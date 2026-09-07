"""Runtime configuration.

Canonical responsibility:
- Holds process-level network and storage configuration for pbl4-runtime.

Important boundary:
- expected_workers is NOT a generic deployment configuration default.
- Worker count and synchronization strategy are provided per-attempt via StrategyContext.

Status:
- Scaffold only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuntimeConfig:
    """Configuration for the Runtime / Parameter Server process.

    Note: expected_workers is NOT a generic deployment configuration default.
    The expected worker count and synchronization strategy are provided per-attempt
    via the resolved training contract and StrategyContext.
    """

    host: str = "127.0.0.1"
    port: int | None = None
    management_port: int | None = None
    checkpoint_dir: str = ""
    log_level: str = "INFO"
