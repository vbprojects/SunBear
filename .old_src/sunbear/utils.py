from typing import Any
from .Schema import Path

def isna(val: Any) -> bool:
    """Check if a value is None or equivalent missing proxy."""
    return val is None

def resolve_path(val: Any, path_segments: list) -> Any:
    for i, p in enumerate(path_segments):
        if isinstance(val, dict):
            val = val.get(p, None)
        elif isinstance(val, list):
            remaining = path_segments[i:]
            return [resolve_path(item, remaining) for item in val]
        else:
            return None
    return val

def set_path(record: dict, path_segments: list, value: Any) -> None:
    """Sets a value in a nested dictionary, creating missing paths as needed."""
    curr = record
    for p in path_segments[:-1]:
        if p not in curr or not isinstance(curr[p], dict):
            curr[p] = {}
        curr = curr[p]
    curr[path_segments[-1]] = value

class Expression:
    """Base class for symbolic evaluators."""
    def evaluate(self, record: Any) -> Any:
        raise NotImplementedError()

class col(Expression):
    """Symbolic evaluator for a column/path."""
    def __init__(self, path_str):
        if isinstance(path_str, tuple):
            self.path = list(path_str)
        elif isinstance(path_str, str):
            self.path = list(Path.parse_depth(path_str))
        elif isinstance(path_str, list):
            self.path = path_str
        else:
            raise TypeError(f"Invalid path type for col: {type(path_str)}")

    def evaluate(self, record: Any) -> Any:
        return resolve_path(record, self.path)

class gen(Expression):
    """Wrapper around a generator to evaluate it once per row."""
    def __init__(self, generator):
        self.generator = generator

    def evaluate(self, record: Any) -> Any:
        try:
            return next(self.generator)
        except StopIteration:
            return None
