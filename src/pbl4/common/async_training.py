"""Validation shared by contract producers and consumers; no process dependencies."""

DEFAULTS = {
    "units_per_contribution": 1,
    "staleness_threshold": 6,
    "reconnect_grace_seconds": 60,
    "assignment_timeout_seconds": 1800,
}
_BOUNDS = {
    "units_per_contribution": (1, 4096),
    "staleness_threshold": (0, 1_000_000),
    "reconnect_grace_seconds": (1, 3600),
    "assignment_timeout_seconds": (1, 86400),
}


def resolve_async_training(value: object = None) -> dict[str, int]:
    if value is not None and not isinstance(value, dict):
        raise ValueError("async_training must be an object")
    raw = {} if value is None else value
    if raw.keys() - DEFAULTS.keys():
        raise ValueError("Unknown async_training setting")
    result = {**DEFAULTS, **raw}
    for name, number in result.items():
        low, high = _BOUNDS[name]
        if type(number) is not int or not low <= number <= high:
            raise ValueError(f"async_training.{name} must be an integer in [{low}, {high}]")
    return result
