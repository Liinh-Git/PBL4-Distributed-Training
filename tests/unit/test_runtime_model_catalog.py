"""A service lifetime can admit jobs with different frozen model manifests."""

from types import SimpleNamespace

import pytest

from pbl4.common.model_profiles import MODEL_PROFILES
from pbl4.runtime.process import RuntimeProcess, _AttemptRunner


def test_jobs_select_their_own_manifest_without_restarting_runtime(tmp_path):
    manifests = {name: SimpleNamespace(parameter_manifest_hash=name) for name in MODEL_PROFILES}
    process = RuntimeProcess(
        host="127.0.0.1",
        dtp_port=0,
        management_port=0,
        dataset_manager_url="http://127.0.0.1:1",
        checkpoint_dir=tmp_path,
        parameter_manifests=manifests,
    )
    runners = []
    for name, profile in MODEL_PROFILES.items():
        runner = _AttemptRunner(
            process=process,
            management=None,
            payload={
                "job_id": name,
                "attempt_id": name,
                "execution_mode": "FRESH",
                "resolved_contract": {
                    "model": {
                        "model_id": name,
                        "profile": profile,
                        "parameter_manifest_hash": name,
                    },
                    "synchronization": {"training_strategy": "strict_bsp", "expected_workers": 2},
                    "checkpoint_policy": {
                        "type": "periodic",
                        "schema_version": 1,
                        "policy_version": 1,
                        "every_n_epochs": 5,
                    },
                    "update_policy": {"type": "plain_sgd"},
                    "protocols": {"dtp_version": 1, "mcp_version": 1},
                },
            },
        )
        runner._validate_contract()
        runners.append(runner)
    assert runners[0]._manifest is manifests[runners[0].job_id]
    assert runners[1]._manifest is manifests[runners[1].job_id]
    runners[1]._payload["resolved_contract"]["model"]["parameter_manifest_hash"] = "wrong"
    with pytest.raises(ValueError, match="incompatible"):
        runners[1]._validate_contract()
