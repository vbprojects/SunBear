"""Strict, dependency-free JSON codec shared by caches and outputs."""

import json
import hashlib


def _json_value(value):
    """Accept only losslessly JSON-roundtrippable values."""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        import math

        if not math.isfinite(value):
            raise TypeError("Non-finite floats are not supported by the JSON codec")
        return value
    if type(value) is list:
        return [_json_value(v) for v in value]
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: _json_value(v) for k, v in value.items()}
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def _encoded(value):
    return json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _hash(value):
    return hashlib.sha256(_encoded(value).encode()).hexdigest()
