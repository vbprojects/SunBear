from typing import Any

def isna(val: Any) -> bool:
    """Check if a value is None or equivalent missing proxy."""
    return val is None
