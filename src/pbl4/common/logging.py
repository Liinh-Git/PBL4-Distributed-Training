"""Logging helper for PBL4.

Provides standard library logging configuration with structured correlation context guidance.
Does not force third-party logging frameworks at bootstrap.

Distributed Correlation Context Fields (when applicable):
- attempt_id: Training attempt identifier
- session_id: Worker registration session (uint64)
- worker_id: Assigned logical worker rank
- operation_id: DTP/1 generic 8-byte correlation identifier
- model_version: Canonical parameter version
- step_id: Step iteration number (StrictBSP projection)
- runtime_event_seq: Monotonic runtime event sequence
- component: Subsystem name (runtime, worker, management_backend, dataset_manager)
"""

from __future__ import annotations

import logging
import sys
import time


def setup_logging(
    *,
    level: str = "INFO",
    component: str = "pbl4",
) -> None:
    """Configure basic standard library logging for a PBL4 process."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    formatter = logging.Formatter(
        fmt=f"%(asctime)s [%(levelname)s] [{component}] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )
    formatter.converter = time.gmtime

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)


def get_logger(name: str) -> logging.Logger:
    """Return a standard library logger."""
    return logging.getLogger(name)
