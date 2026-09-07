"""Management Backend API — Job endpoints.

Canonical responsibility:
- Exposes REST endpoints for job submission, listing, and inspection.
- Delegates business validation to JobService.

Important boundary:
- Validates job specifications without launching runtime execution directly.

Status:
- Scaffold only.
"""

from __future__ import annotations
