"""Management Backend API — Runtime control endpoints.

Canonical responsibility:
- Exposes REST endpoints for querying runtime status and issuing control commands.
- Forwards commands to Runtime via RuntimeGateway.

Important boundary:
- Interacts with Runtime only through RuntimeGateway (MCP/1).
- Does NOT import Runtime training internals directly.

Status:
- Scaffold only.
"""

from __future__ import annotations
