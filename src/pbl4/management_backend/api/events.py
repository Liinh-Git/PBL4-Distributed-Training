"""Management Backend API — Event querying and subscription endpoints.

Canonical responsibility:
- Exposes REST endpoints for querying recorded training events and audit trails.
- Reads event history persisted in PostgreSQL by EventIngest.

Important boundary:
- Operates on persisted event records; does NOT receive live events directly from Runtime.

Status:
- Scaffold only.
"""

from __future__ import annotations
