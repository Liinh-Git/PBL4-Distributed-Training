"""Strategy selection from the resolved contract, without fallback."""

from pbl4.runtime.synchronization.base import SynchronizationPolicy
from pbl4.runtime.synchronization.context import StrategyContext
from pbl4.runtime.synchronization.strict_bsp import StrictBSP


def create_policy(context: StrategyContext) -> SynchronizationPolicy:
    if context.training_strategy != "strict_bsp":
        raise ValueError("UNSUPPORTED_TRAINING_STRATEGY")
    return StrictBSP(context)
