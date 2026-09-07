"""Time utilities for PBL4.

Provides consistent timestamp generation across all components.
All timestamps are UTC.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def monotonic_ms() -> int:
    """Return monotonic clock value in milliseconds.

    Suitable for measuring elapsed time within a single process.
    NOT suitable for cross-process correlation.
    """
    return int(time.monotonic() * 1000)
