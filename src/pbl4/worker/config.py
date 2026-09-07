"""Worker configuration.

Canonical responsibility:
- Holds process deployment configuration for a training worker (host, ports, paths).

Important boundary:
- worker_id is NOT configured here; logical rank is assigned by Runtime during registration.
- Does NOT configure cluster-wide expected_workers or synchronization strategies.

Status:
- Scaffold only.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorkerConfig:
    """Configuration for a Worker process.

    Workers start without an assigned logical rank. The logical worker_id (0..N-1)
    is assigned by Runtime during registration/session establishment.
    """

    node_label: str = "node-unknown"
    runtime_host: str = "127.0.0.1"
    runtime_port: int | None = None
    cache_dir: str = ""
    log_level: str = "INFO"
