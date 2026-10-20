"""Unit tests for CheckpointPolicy epoch cadence and validation."""

import pytest

from pbl4.runtime.checkpoint_policy import CheckpointPolicy


def test_checkpoint_policy_initialization_and_validation():
    # Valid periodic policy
    policy = CheckpointPolicy(every_n_epochs=5)
    assert policy.every_n_epochs == 5
    assert policy.checkpoint_policy == "periodic"
    assert policy.policy_version == 1
    assert policy.max_attempts == 3

    # Must reject unsupported policies
    with pytest.raises(ValueError, match="Unsupported checkpoint policy"):
        CheckpointPolicy(every_n_epochs=5, checkpoint_policy="after_each_model_update_blocking")

    with pytest.raises(ValueError, match="Unsupported checkpoint policy"):
        CheckpointPolicy(every_n_epochs=5, checkpoint_policy="step_based")

    # Must reject non-positive or non-int every_n_epochs
    with pytest.raises(ValueError, match="every_n_epochs must be a positive integer"):
        CheckpointPolicy(every_n_epochs=0)

    with pytest.raises(ValueError, match="every_n_epochs must be a positive integer"):
        CheckpointPolicy(every_n_epochs=-1)

    with pytest.raises(ValueError, match="every_n_epochs must be a positive integer"):
        CheckpointPolicy(every_n_epochs=5.0)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="every_n_epochs must be a positive integer"):
        CheckpointPolicy(every_n_epochs=True)  # type: ignore[arg-type]

    # Must reject invalid policy version
    with pytest.raises(ValueError, match="Unsupported checkpoint policy version"):
        CheckpointPolicy(every_n_epochs=5, policy_version=2)

    # Must reject invalid max_attempts
    with pytest.raises(ValueError, match="Invalid checkpoint attempt limit"):
        CheckpointPolicy(every_n_epochs=5, max_attempts=0)


@pytest.mark.parametrize(
    "n,completed_epoch,expected_due",
    [
        # N=1: due every completed epoch (1, 2, 3, ...)
        (1, 0, False),
        (1, 1, True),
        (1, 2, True),
        (1, 3, True),
        # N=2: due at 2, 4, 6...
        (2, 0, False),
        (2, 1, False),
        (2, 2, True),
        (2, 3, False),
        (2, 4, True),
        # N=5: due at 5, 10...
        (5, 0, False),
        (5, 1, False),
        (5, 4, False),
        (5, 5, True),
        (5, 6, False),
        (5, 9, False),
        (5, 10, True),
        # N=10: due at 10, 20...
        (10, 5, False),
        (10, 10, True),
    ],
)
def test_due_epoch_table_driven(n: int, completed_epoch: int, expected_due: bool):
    policy = CheckpointPolicy(every_n_epochs=n)
    assert policy.due_epoch(completed_epoch) == expected_due


def test_may_retry_caps_at_max_attempts():
    policy = CheckpointPolicy(every_n_epochs=5, max_attempts=3)
    assert policy.may_retry(0) is True
    assert policy.may_retry(1) is True
    assert policy.may_retry(2) is True
    assert policy.may_retry(3) is False
    assert policy.may_retry(4) is False
