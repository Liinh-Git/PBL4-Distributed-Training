"""Strategy selection from the resolved contract, without fallback."""

from pbl4.runtime.synchronization.async_sgd import AsyncSGD
from pbl4.runtime.synchronization.context import StrategyContext
from pbl4.runtime.synchronization.strict_bsp import StrictBSP


def create_policy(context: StrategyContext, *, learning_rate=1.0, staleness_threshold=6):
    if context.training_strategy == "async_sgd":
        return AsyncSGD(context.attempt_id, learning_rate, staleness_threshold)
    if context.training_strategy != "strict_bsp":
        raise ValueError("UNSUPPORTED_TRAINING_STRATEGY")
    return StrictBSP(context)
