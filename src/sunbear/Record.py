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
        """Recursive get/set/delete over ``node`` guided by nested-dict path.

        action: "get" | "set" | "delete"
        - "get": returns leaf value, or None if missing or node not a dict
        - "set": creates intermediate dicts as needed, assigns value at leaf
        - "delete": pops leaf, no-op if missing

        Lists are transparently traversed: when the walker encounters a list
        at an intermediate position in the path (e.g. ``facets.features``
        where ``facets`` is a list of dicts), it walks each list element
        with the remaining path and collects the results into a list.
        """
        if not path:
            return node if action == "get" else None
        # --- list transparency: walk into each element ---
        if isinstance(node, list):
            if action == "get":
                results = []
                for item in node:
                    r = Record._walk(item, path, action, value)
                    if r is not None:
                        results.append(r)
                return results if results else None
            return None
        if not isinstance(node, dict):
            return None if action == "get" else None
        for k, sub in path.items():
            if isinstance(sub, dict) and sub:
                child = node.get(k)
                if child is None:
                    if action == "set":
                        node[k] = {}
                        child = node[k]
                    else:
                        return None if action == "get" else None
                result = Record._walk(child, sub, action, value)
                if action == "get":
                    return result
            else:
                if action == "get":
                    return node.get(k)
                if action == "set":
                    node[k] = value
                elif action == "delete":
                    node.pop(k, None)
        return None

    # ---- public API ----

    def get(self, indexer):
        return self._walk(self.data, self.resolve(indexer), "get")

    def set(self, indexer, value) -> "Record":
        self._walk(self.data, self.resolve(indexer), "set", value)
        return self

    def delete(self, indexer) -> "Record":
        self._walk(self.data, self.resolve(indexer), "delete")
        return self

    def add(self, indexer, value) -> "Record":
        """Set only if missing (treats None as missing)."""
        if self.get(indexer) is None:
            self.set(indexer, value)
        return self

    def mv(self, src, dst) -> "Record":
        """Move value from src path to dst path."""
        v = self.get(src)
        self.delete(src)
        if v is not None:
            self.set(dst, v)
        return self

    def cpy(self, src, dst) -> "Record":
        """Copy value from src path to dst path (keeps src)."""
        v = self.get(src)
        if v is not None:
            self.set(dst, v)
        return self

    # ---- sugar ----

    def __getitem__(self, indexer):
        return self.get(indexer)

    def __setitem__(self, indexer, value):
        self.set(indexer, value)

    def __contains__(self, indexer) -> bool:
        return self.get(indexer) is not None
