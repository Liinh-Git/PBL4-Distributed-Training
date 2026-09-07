"""Management Backend API — Checkpoint catalog endpoints.

Canonical responsibility:
- Exposes REST endpoints for querying checkpoint metadata and catalog history.
- Indexes checkpoint events emitted by Runtime over MCP/1.

Important boundary:
- Does NOT store or transfer raw checkpoint tensor files (Runtime manages disk files).

Status:
- Scaffold only.
"""

from __future__ import annotations
