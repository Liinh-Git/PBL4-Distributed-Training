"""Management Backend API — Attempt endpoints.

Canonical responsibility:
- Exposes REST endpoints for attempt launch, monitoring, and state inspection.
- Delegates business logic to AttemptService.

Important boundary:
- Does NOT participate in training-step synchronization or handle raw tensors.

Status:
- Scaffold only.
"""

from __future__ import annotations
