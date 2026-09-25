"""PBL4 Node Agent package.

Manages Node identity, telemetry reporting, and local Worker process supervision.
"""

from __future__ import annotations

from pbl4.node_agent.client import NodeAgentClient
from pbl4.node_agent.config import NodeAgentConfig
from pbl4.node_agent.enrollment import enroll
from pbl4.node_agent.identity import (
    NodeIdentity,
    identity_path,
    load_identity,
    save_identity,
)
from pbl4.node_agent.supervisor import (
    LOCAL_STATE_FAILED,
    LOCAL_STATE_RUNNING,
    LOCAL_STATE_STARTING,
    LOCAL_STATE_STOPPED,
    VALID_LOCAL_STATES,
    LocalAllocationRecord,
    WorkerProcessSupervisor,
)
from pbl4.node_agent.telemetry import (
    collect_static_capabilities,
    sample_resources,
)

__all__ = [
    "LOCAL_STATE_FAILED",
    "LOCAL_STATE_RUNNING",
    "LOCAL_STATE_STARTING",
    "LOCAL_STATE_STOPPED",
    "VALID_LOCAL_STATES",
    "LocalAllocationRecord",
    "NodeAgentClient",
    "NodeAgentConfig",
    "NodeIdentity",
    "WorkerProcessSupervisor",
    "collect_static_capabilities",
    "enroll",
    "identity_path",
    "load_identity",
    "sample_resources",
    "save_identity",
]
