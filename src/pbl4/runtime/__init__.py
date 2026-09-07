"""Runtime — Parameter Server and training coordinator.

Reference: Canonical Runtime / Parameter Server Design (Google Drive)

This package owns the server-side training lifecycle:
- Coordinator: Attempt lifecycle owner
- ParameterServer: DTP/1 endpoint, connection handling
- WorkerRegistry: membership / session management
- CanonicalModel: single-writer model state
- UpdateEngine: sample-weighted gradient aggregation → parameter update
- SynchronizationPolicy: admission / update-ready decisions
- CheckpointPolicy: checkpoint cadence decisions
- CheckpointManager: durability mechanism
- EventEmitter: bounded runtime event queue for MCP delivery

Console entrypoint: pbl4.runtime.entrypoint:main
"""

from __future__ import annotations
