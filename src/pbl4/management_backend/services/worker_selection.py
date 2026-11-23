"""Management-only placement lookup shared by preview and attempt creation."""

from pbl4.management_backend.repositories import allocation_repository, node_repository
from pbl4.management_backend.services.cluster_scheduler import ClusterScheduler


def select_workers(conn, *, expected_workers=None, node_ids=None, for_update=False):
    nodes = node_repository.list_nodes(
        conn, state=node_repository.NODE_STATE_ONLINE, limit=None, for_update=for_update
    )
    if node_ids is not None and not set(node_ids).issubset({node["node_id"] for node in nodes}):
        raise ValueError("Selected Nodes must all exist and be ONLINE.")
    return ClusterScheduler.select_placements(
        expected_workers=expected_workers,
        nodes=nodes,
        active_allocations=allocation_repository.list_active(conn),
        node_ids=node_ids,
    )
