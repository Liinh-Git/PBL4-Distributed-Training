"""Management Backend API — Dataset endpoints.

Canonical responsibility:
- Exposes REST endpoints for dataset ingestion initiation and build status queries.
- Serves catalog and manifest metadata to CLI and WebUI.

Important boundary:
- Queries Dataset Manager for status; does NOT self-infer READY.
- Does NOT proxy shard downloads for workers.

Status:
- Scaffold only.
"""

from __future__ import annotations
