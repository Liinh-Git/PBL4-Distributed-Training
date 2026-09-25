"""Unit tests asserting SynchronizationRegistry immutability under DBS.

Normative constraint: AGENTS.md Rule 17 & docs/DBS_DESIGN.md Section 4:
DBS is workload scheduling under StrictBSP. The training_strategy MUST remain
strict_bsp exclusively. Do not introduce dbs_bsp, DbsStrictBSP, or any other
synchronization strategy.
"""

import pytest

from pbl4.runtime.synchronization.context import Member, StrategyContext
from pbl4.runtime.synchronization.registry import create_policy
from pbl4.runtime.synchronization.strict_bsp import StrictBSP


def _make_context(strategy: str = "strict_bsp", n: int = 3) -> StrategyContext:
    return StrategyContext(
        job_id="test-job",
        attempt_id="test-attempt",
        contract_hash="contract-hash",
        training_strategy=strategy,
        expected_workers=n,
        update_policy="plain_sgd",
        dataset_build_id="dataset-build-1",
        dataset_manifest_hash="dataset-hash",
        parameter_manifest_hash="param-hash",
        protocol_version=1,
        total_numel=100,
        membership=tuple(Member(w, w + 100) for w in range(n)),
    )


def test_registry_creates_strict_bsp():
    ctx = _make_context(strategy="strict_bsp")
    policy = create_policy(ctx)
    assert isinstance(policy, StrictBSP)
    assert policy.context.training_strategy == "strict_bsp"


@pytest.mark.parametrize(
    "forbidden_strategy",
    [
        "dbs",
        "dbs_bsp",
        "DbsStrictBSP",
        "dynamic_batch_size",
        "strict_bsp_dbs",
        "async_ps",
        "fed_avg",
    ],
)
def test_registry_strictly_rejects_dbs_as_synchronization_strategy(forbidden_strategy: str):
    ctx = _make_context(strategy=forbidden_strategy)
    with pytest.raises(ValueError, match="UNSUPPORTED_TRAINING_STRATEGY"):
        create_policy(ctx)
