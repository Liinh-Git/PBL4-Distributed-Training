"""Management Backend — management/application layer.

Reference: Canonical Backend Architecture (Google Drive)

The Management Backend provides:
- REST API for CLI/WebUI
- WebSocket for real-time updates
- Database persistence (PostgreSQL via psycopg)
- MCP/1 gateway to Runtime
- Dataset Manager coordination

The Management Backend MUST NOT:
- Import ParameterServer implementation
- Contain gradient/tensor path code
- Self-infer READY for Dataset Build
- Use DB as a synchronization primitive

Management Backend down != training down.
Console entrypoint: pbl4.management_backend.entrypoint:main
"""

from __future__ import annotations
