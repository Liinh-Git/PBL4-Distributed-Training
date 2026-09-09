"""Pure server-side plain SGD arithmetic. No model mutation privileges."""

import math

import numpy as np


class SGDUpdater:
    def update(
        self, parameters: np.ndarray, gradient: np.ndarray, learning_rate: float
    ) -> np.ndarray:
        if (
            parameters.dtype != np.float32
            or gradient.dtype != np.float32
            or parameters.ndim != 1
            or parameters.shape != gradient.shape
            or not parameters.size
        ):
            raise ValueError("Incompatible FP32 update operands")
        if not math.isfinite(learning_rate) or learning_rate <= 0:
            raise ValueError("Learning rate must be finite and positive")
        if not np.isfinite(parameters).all() or not np.isfinite(gradient).all():
            raise ValueError("Nonfinite update operand")
        with np.errstate(over="raise", invalid="raise"):
            candidate = parameters - np.float32(learning_rate) * gradient
        if not np.isfinite(candidate).all():
            raise ValueError("Nonfinite update candidate")
        return candidate
