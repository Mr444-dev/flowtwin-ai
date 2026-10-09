from __future__ import annotations

import math
from collections.abc import Sequence


def weighted_quantile(values: Sequence[float], weights: Sequence[float], quantile: float) -> float:
    """Return the inverse empirical weighted CDF at ``quantile``."""
    if len(values) != len(weights) or len(values) == 0:
        raise ValueError("values and weights must have the same non-zero length")
    if not 0 <= quantile <= 1:
        raise ValueError("quantile must be between 0 and 1")

    pairs: list[tuple[float, float]] = []
    for value, weight in zip(values, weights):
        value_number = float(value)
        weight_number = float(weight)
        if not math.isfinite(value_number) or not math.isfinite(weight_number) or weight_number < 0:
            raise ValueError("values and weights must be finite; weights cannot be negative")
        if weight_number > 0:
            pairs.append((value_number, weight_number))
    if not pairs:
        raise ValueError("at least one weight must be positive")

    pairs.sort(key=lambda pair: pair[0])
    threshold = quantile * sum(weight for _, weight in pairs)
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= threshold:
            return value
    return pairs[-1][0]
