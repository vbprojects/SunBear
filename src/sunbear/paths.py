"""Typed path segments and the missing-value marker."""
from dataclasses import dataclass

class _Missing:
    def __repr__(self):
        return "MISSING"
    def __bool__(self):
        raise TypeError("Missing values have no truth value; use exists() or fill_missing()")
    def __copy__(self):
        return self
    def __deepcopy__(self, memo):
        return self

MISSING = _Missing()

@dataclass(frozen=True)
class Key:
    value: str

@dataclass(frozen=True)
class Index:
    value: int

@dataclass(frozen=True)
class Traverse:
    pass

@dataclass(frozen=True)
class PathSpec:
    segments: tuple

    @classmethod
    def dotted(cls, text):
        return cls(tuple(Key(k) for k in text.split(".")) if text else ())

    def append(self, key):
        if isinstance(key, str):
            segment = Key(key)
        elif isinstance(key, int) and not isinstance(key, bool):
            segment = Index(key)
        elif key is Ellipsis:
            segment = Traverse()
        else:
            raise TypeError("Path brackets require a string, integer, or ...")
        return PathSpec(self.segments + (segment,))

    def __str__(self):
        return "".join(f"[{s.value!r}]" if isinstance(s, (Key, Index)) else "[...]"
                       for s in self.segments)


def output_value(value):
    """Omit missing object fields; reject missing array positions."""
    if isinstance(value, dict):
        return {k: output_value(v) for k, v in value.items() if v is not MISSING}
    if isinstance(value, list):
        if any(v is MISSING for v in value):
            raise ValueError("Missing values cannot occupy array positions")
        return [output_value(v) for v in value]
    return value
