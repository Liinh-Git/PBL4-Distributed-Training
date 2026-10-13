"""Optional Node choice is execution data; frozen training semantics stay intact."""

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from pbl4.management_backend.services import attempt_service


@pytest.mark.parametrize(
    "selection", [["b", "c", "d"], ["a", "a", "c"], ["a", "b"], ["a", "b", "offline"]]
)
def test_selected_nodes_are_exact_online_distinct_members(selection):
    contract = {
        "dataset": {"dataset_build_id": "build"},
        "synchronization": {"expected_workers": 3},
    }
    original = deepcopy(contract)
    nodes = [{"node_id": n, "state": "ONLINE", "capabilities_jsonb": {}} for n in "abcd"]
    with (
        patch.object(
            attempt_service.dataset_build_repository, "get_build", return_value={"state": "READY"}
        ),
        patch.object(attempt_service.node_repository, "list_nodes", return_value=nodes),
        patch.object(attempt_service.allocation_repository, "list_active", return_value=[]),
    ):
        if selection == ["b", "c", "d"]:
            placements = attempt_service._preflight_job_and_select_placements(
                MagicMock(), {"job_id": "job"}, contract, node_ids=selection
            )
            assert [p.node_id for p in placements] == selection
        else:
            with pytest.raises(attempt_service.JobValidationError):
                attempt_service._preflight_job_and_select_placements(
                    MagicMock(), {"job_id": "job"}, contract, node_ids=selection
                )
    assert contract == original
