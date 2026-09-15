"""Record.py — row payload with single _walk for get/set/delete + metadata.

Minimal, iterator-friendly record:
- `data` is the underlying dict (mutable, shared by reference per design)
- `meta` is a free-form dict for plan annotations and lazy skip-flags
- `_walk(node, path, action, value)` is the ONLY recursive helper
- `_freeze(v)` produces hashable keys for group_by / join indices
- `_mkpath(s)` converts a dotted string to a nested-dict path
"""
from __future__ import annotations
from typing import Any
import copy
from .paths import MISSING, PathSpec, Key, Index, Traverse, output_value


# ═══════════════════════════════════════════════════════════════════════════
# _freeze: hashable projection for group_by / join keys
# ═══════════════════════════════════════════════════════════════════════════

def _freeze(v: Any) -> Any:
    """Make v hashable so it can serve as a dict key in indices.

    Lists → tuples; dicts → sorted tuples of (k, frozen_v); everything else
    passes through unchanged.
    """
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    return v


# ═══════════════════════════════════════════════════════════════════════════
# _mkpath: dotted-string indexer → nested-dict path
# ═══════════════════════════════════════════════════════════════════════════

def _mkpath(s: str) -> dict:
    """``"a.b.c"`` → ``{"a": {"b": {"c": {}}}}``. Empty string → ``{}``."""
    if not s:
        return {}
    out: dict = {}
    cur = out
    for k in s.split("."):
        cur[k] = {}
        cur = cur[k]
    return out


def _deep_merge(dst: dict, src: dict) -> dict:
    """Recursively merge src into dst in-place."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


# ═══════════════════════════════════════════════════════════════════════════
# Record
# ═══════════════════════════════════════════════════════════════════════════

class Record:
    """Row payload. ``data`` is the dict; ``meta`` is plan/skip annotation."""

    __slots__ = ("data", "meta")

    def __init__(self, data: dict | None = None, meta: dict | None = None):
        self.data = data if data is not None else {}
        self.meta = meta if meta is not None else {}

    def __repr__(self) -> str:
        return f"Record({self.data!r})"

    def __eq__(self, other) -> bool:
        return isinstance(other, Record) and self.data == other.data

    __hash__ = None

    # ---- indexer resolution ----

    @classmethod
    def resolve(cls, indexer) -> dict:
        """Normalize any indexer to a nested-dict path.

        Path/Col (Expr leaves)  → extract ``.indexer`` and resolve
        str     → _mkpath(s)
        dict    → pass through
        tuple/list of str → _deep_merge of all _mkpath results
        """
        # Expr leaf nodes (Path, Col) carry their own indexer
        ix = getattr(indexer, "indexer", None)
        if isinstance(ix, PathSpec):
            indexer = ix
        if isinstance(indexer, PathSpec):
            out = {}
            cur = out
            for seg in indexer.segments:
                key = seg.value if isinstance(seg, (Key, Index)) else seg
                cur[key] = {}
                cur = cur[key]
            return out
        if ix is not None and isinstance(ix, str):
            return _mkpath(ix) if ix else {}
        if isinstance(indexer, dict):
            return indexer
        if isinstance(indexer, str):
            return _mkpath(indexer)
        if isinstance(indexer, (list, tuple)):
            merged: dict = {}
            for sub in indexer:
                _deep_merge(merged, cls.resolve(sub))
            return merged
        raise TypeError(f"unsupported indexer: {indexer!r}")

    # ---- single recursive walker ----

    @staticmethod
    def _walk(node, path: dict, action: str, value=None):
        if not path:
            return node if action == "get" else None
        results = []
        for k, sub in path.items():
            if isinstance(node, list) and not isinstance(k, int):
                rest = sub if isinstance(k, Traverse) else {k: sub}
                if action == "get":
                    values = [Record._walk(item, rest, action) for item in node]
                    results.append([v for v in values if v is not MISSING])
                elif not rest:
                    if action == "delete":
                        node.clear()
                    elif value is MISSING:
                        raise ValueError("Missing values cannot occupy array positions")
                    else:
                        node[:] = [copy.deepcopy(output_value(value)) for _ in node]
                else:
                    for i, item in enumerate(node):
                        if isinstance(item, (dict, list)):
                            node[i] = copy.copy(item)
                            Record._walk(node[i], rest, action, value)
                continue
            valid = isinstance(node, dict) and isinstance(k, str)
            if isinstance(node, list) and isinstance(k, int):
                valid = -len(node) <= k < len(node)
                if not valid and action == "set":
                    raise IndexError(f"Array index {k} is out of range")
            if not valid:
                if action == "get":
                    results.append(MISSING)
                elif action == "set":
                    raise TypeError("Path does not match the container type")
                continue
            child = node.get(k, MISSING) if isinstance(node, dict) else node[k]
            if sub:
                if action == "get":
                    results.append(Record._walk(child, sub, action))
                elif child is not MISSING or action == "set":
                    if child is MISSING:
                        child = [] if isinstance(next(iter(sub)), int) else {}
                    if isinstance(child, (dict, list)):
                        child = copy.copy(child)
                    Record._walk(child, sub, action, value)
                    node[k] = child
            elif action == "get":
                results.append(child)
            elif action == "set":
                if value is MISSING:
                    if isinstance(node, list):
                        raise ValueError("Missing values cannot occupy array positions")
                    node.pop(k, None)
                else:
                    node[k] = copy.deepcopy(output_value(value))
            elif action == "delete":
                if isinstance(node, dict):
                    node.pop(k, None)
                else:
                    del node[k]
        return results[0] if results else MISSING

    # ---- public API ----

    def get(self, indexer, default=None):
        value = self._walk(self.data, self.resolve(indexer), "get")
        return default if value is MISSING else value

    def set(self, indexer, value) -> "Record":
        self._walk(self.data, self.resolve(indexer), "set", value)
        return self

    def delete(self, indexer) -> "Record":
        self._walk(self.data, self.resolve(indexer), "delete")
        return self

    def add(self, indexer, value) -> "Record":
        """Set only if absent; preserve explicit null."""
        if self.get(indexer, MISSING) is MISSING:
            self.set(indexer, value)
        return self

    def mv(self, src, dst) -> "Record":
        """Move value from src path to dst path."""
        v = self.get(src, MISSING)
        self.delete(src)
        if v is not MISSING:
            self.set(dst, v)
        return self

    def cpy(self, src, dst) -> "Record":
        """Copy value from src path to dst path (keeps src)."""
        v = self.get(src, MISSING)
        if v is not MISSING:
            self.set(dst, v)
        return self

    # ---- sugar ----

    def __getitem__(self, indexer):
        return self.get(indexer)

    def __setitem__(self, indexer, value):
        self.set(indexer, value)

    def __contains__(self, indexer) -> bool:
        return self.get(indexer, MISSING) is not MISSING
