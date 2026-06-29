"""Program.py — deferred expr pipeline with row-based caching.

A Program stores a sequence of **expr statements** (tuples from
``assign()``, ``keep()``, ``filter_field()``, etc.) and replays them on a
DataTree when called.  Caching is **row-based**: each input record is hashed
individually; cache hits return the stored output, cache misses run the full
expr pipeline on a single-row DataTree and store the result.

Usage::

    from sunbear import Program
    from sunbear.expr import b, assign, keep

    prog = Program().expr(
        assign(b.status, "active"),
        keep(b.age >= 18),
    )

    result = prog(dt)          # execute (with caching)
    result2 = prog(dt)         # cache hit — rows skipped

    # Pipe syntax:
    result = dt | prog

    # Load all cached rows as a standalone DataTree:
    dt_from_cache = prog.to_DataTree()

    # Custom cache name (otherwise auto-hashed from stmts):
    prog = Program(name="adult_pipeline").expr(...)
    prog = Program(cache=FileCache("adult_pipeline")).expr(...)
"""
from __future__ import annotations

import abc
import hashlib
import json
import os
import time as _time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .DataTree import DataTree


# Sentinel: a cached None means "row was filtered out"
_FILTERED = object()


# ═══════════════════════════════════════════════════════════════════════════
# Hashing helpers
# ═══════════════════════════════════════════════════════════════════════════

def _stable_hash(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


class _StmtEncoder(json.JSONEncoder):
    """Encode expr stmts to stable JSON (Expr nodes → repr, callables → repr)."""

    def default(self, obj):
        if callable(obj):
            return {"__callable__": repr(obj)}
        from .expr.ast import Expr as _Expr
        if isinstance(obj, _Expr):
            return {"__expr__": repr(obj)}
        return super().default(obj)


def _row_hash(data: dict) -> str:
    """Hash a record's data dict into a stable short key."""
    raw = json.dumps(data, sort_keys=True, default=str)
    return _stable_hash(raw)


# ═══════════════════════════════════════════════════════════════════════════
# AbstractCache
# ═══════════════════════════════════════════════════════════════════════════

class AbstractCache(abc.ABC):
    """Row-based cache: maps row_hash → output dict | None.

    Return ``_FILTERED`` from ``get()`` to indicate the row was removed by
    a ``keep`` / ``filter`` statement and should be skipped on replay.
    Return ``None`` from ``get()`` when the row_key is not in the cache.
    """

    @abc.abstractmethod
    def get(self, row_key: str) -> dict | None | object:
        """Return cached output for *row_key*.

        - ``dict``   → cached output row
        - ``_FILTERED`` → row was filtered out (skip)
        - ``None``   → not in cache (miss)
        """
        ...

    @abc.abstractmethod
    def set(self, row_key: str, output: dict | None) -> None:
        """Cache *output* for *row_key*.  Pass ``None`` for filtered rows."""
        ...

    def to_DataTree(self) -> "DataTree":
        """Reconstruct a DataTree from all cached (non-filtered) rows."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support to_DataTree()"
        )


# ═══════════════════════════════════════════════════════════════════════════
# FileCache — JSON-file backend
# ═══════════════════════════════════════════════════════════════════════════

_CACHE_DIR = ".sunbear_cache"


class FileCache(AbstractCache):
    """JSON-file cache at ``.sunbear_cache/{name}.json``.

    File format::

        { "<row_key>": { "data": {...} | null, "ts": <epoch> }, ... }

    ``data: null`` means the row was filtered out.
    """

    def __init__(self, name: str):
        self.name = name
        os.makedirs(_CACHE_DIR, exist_ok=True)
        self._path = os.path.join(_CACHE_DIR, f"{name}.json")
        self._store: dict[str, Any] = {}
        self._dirty = False
        self._load()

    # ---- persistence ----

    def _load(self) -> None:
        if os.path.exists(self._path):
            with open(self._path, "r", encoding="utf-8") as f:
                self._store = json.load(f)

    def _save(self) -> None:
        if not self._dirty:
            return
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._store, f, indent=2, default=str)
        self._dirty = False

    # ---- AbstractCache interface ----

    def get(self, row_key: str) -> dict | None | object:
        entry = self._store.get(row_key)
        if entry is None:
            return None  # not in cache
        data = entry.get("data")
        if data is None:
            return _FILTERED  # cached as filtered
        return data

    def set(self, row_key: str, output: dict | None) -> None:
        self._store[row_key] = {"data": output, "ts": _time.time()}
        self._dirty = True
        self._save()

    def to_DataTree(self) -> "DataTree":
        """Load all cached non-filtered rows as a DataTree."""
        rows = []
        for entry in self._store.values():
            data = entry.get("data")
            if data is not None:
                rows.append(data)
        if not rows:
            raise ValueError(f"Cache '{self.name}' has no non-filtered rows")
        from .DataTree import DataTree
        return DataTree.from_records(rows)


# ═══════════════════════════════════════════════════════════════════════════
# Program
# ═══════════════════════════════════════════════════════════════════════════

class Program:
    """Deferred expr pipeline with row-based caching.

    Stores expr statements (tuples) and replays them row-by-row when called.
    Each input record is hashed; cache hits are returned immediately, cache
    misses run the full pipeline on a single-row DataTree.

    ::

        prog = Program().expr(
            assign(b.status, "active"),
            keep(b.age >= 18),
        )
        result = prog(dt)
    """

    def __init__(self, cache: AbstractCache | None = None,
                 name: str | None = None):
        self._statements: list = []
        self._name = name
        self._cache = cache

    # ---- repr ----

    def __repr__(self) -> str:
        label = self._name or "<auto>"
        return f"Program({label!r}, {len(self._statements)} stmts)"

    # ---- program key (cache namespace) ----

    def _program_key(self) -> str:
        """Stable key for this program's stmts.  Used as the FileCache name
        when no explicit cache/name is provided."""
        if self._name is not None:
            return self._name
        raw = json.dumps(self._statements, cls=_StmtEncoder, sort_keys=True)
        return _stable_hash(raw)

    # ---- expr (the only pipeline method) ----

    def expr(self, *statements) -> "Program":
        """Store expr statements for deferred execution."""
        from .expr.lower import _flatten_stmts
        self._statements.extend(_flatten_stmts(statements))
        return self

    # ---- execution ----

    def __call__(self, dt: "DataTree") -> "DataTree":
        """Execute the expr pipeline on *dt*, row by row, with caching.

        Returns a lazy DataTree backed by a generator — rows are produced
        on demand as the caller iterates/collects/scans.  This allows
        ``prog(lazy_dt)`` to stay lazy even when *dt* is a streaming
        source (e.g. from a WebSocket or file).
        """
        from .DataTree import DataTree
        from .expr.lower import run_expr

        # Lazily resolve cache.
        cache = self._cache
        if cache is None:
            cache = FileCache(self._program_key())
            self._cache = cache

        stmts = self._statements

        def _iter_output():
            for record, meta in dt.scan():
                rk = _row_hash(record.data)
                cached = cache.get(rk)

                if cached is _FILTERED:
                    # Row was filtered out in a previous run — skip.
                    continue
                if cached is not None:
                    # Cache hit — use stored output.
                    yield dict(cached)
                    continue

                # Cache miss — run pipeline on a single-row DataTree.
                single = DataTree.from_records([record.data])
                result = run_expr(single, *stmts)
                result_rows = result.collect()

                if not result_rows:
                    # Row was filtered out by keep/filter.
                    cache.set(rk, None)
                    continue

                output = result_rows[0]
                cache.set(rk, output)
                yield dict(output)

        return DataTree.from_iter(_iter_output())

    # ---- to_DataTree ----

    def to_DataTree(self) -> "DataTree":
        """Load all cached rows as a standalone DataTree."""
        if self._cache is None:
            raise RuntimeError("No cache configured — cannot load DataTree")
        return self._cache.to_DataTree()
