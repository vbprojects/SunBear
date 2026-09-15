"""Immutable compiled programs, explicit memoization, and strict JSON caches."""
from __future__ import annotations

import abc
import copy
import hashlib
import json
import os
import tempfile
import warnings
from pathlib import Path
from .Record import Record
from .paths import MISSING, PathSpec
from .expr.ast import Expr, Lit, Path as ExprPath, Col, BinOp, UnOp, Call
from .expr.lower import compile_plan, _flatten_stmts

_FILTERED = object()


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
    return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_encoded(value).encode()).hexdigest()


def _normalize(value, version):
    if value is MISSING:
        return {"missing": True}
    if isinstance(value, PathSpec):
        return {"path": [[type(s).__name__, getattr(s, "value", None)] for s in value.segments]}
    if isinstance(value, (ExprPath, Col)):
        ix = value.indexer
        return _normalize(PathSpec.dotted(ix) if isinstance(ix, str) else ix, version)
    if isinstance(value, Lit):
        return {"literal": _normalize(value.value, version)}
    if isinstance(value, BinOp):
        return {"binary": [value.op, _normalize(value.left, version), _normalize(value.right, version)]}
    if isinstance(value, UnOp):
        return {"unary": [value.op, _normalize(value.operand, version)]}
    if isinstance(value, Call):
        from .expr.eval import FUNCS, BUILTIN_FUNCS
        if FUNCS.get(value.name) is not BUILTIN_FUNCS.get(value.name) and not version:
            raise ValueError("Caching custom registered functions requires cache_version")
        return {"call": [value.name, _normalize(value.args, version), _normalize(value.kwargs, version)]}
    if callable(value):
        if not version:
            raise ValueError("Caching callbacks requires an explicit cache_version")
        return {"callback": [getattr(value, "__module__", ""),
                             getattr(value, "__qualname__", type(value).__qualname__), version]}
    if isinstance(value, tuple):
        return {"tuple": [_normalize(v, version) for v in value]}
    if isinstance(value, list):
        return [_normalize(v, version) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v, version) for k, v in value.items()}
    return _json_value(value)


class AbstractCache(abc.ABC):
    @abc.abstractmethod
    def get(self, row_key):
        """Return dict, _FILTERED, or None for a cache miss."""
    @abc.abstractmethod
    def set(self, row_key, output):
        """Store a dict, or None for a filtered input."""
    def flush(self):
        pass
    def to_DataTree(self):
        raise NotImplementedError


class FileCache(AbstractCache):
    """Strict JSON memoization. One writer per file; writes are atomic and batched."""
    def __init__(self, name, *, directory=".sunbear_cache", flush_every=100):
        if not isinstance(name, str) or not name or Path(name).name != name or name in {".", ".."}:
            raise ValueError("Cache name must be a simple filename")
        if type(flush_every) is not int or flush_every < 1:
            raise ValueError("flush_every must be a positive integer")
        self.name = name
        self._path = str(Path(directory) / (name + ".json"))
        self.flush_every = flush_every
        self._store = {}
        self._pending = 0
        if os.path.exists(self._path):
            with open(self._path, encoding="utf-8") as f:
                payload = json.load(f)
            if payload.get("format") != 1:
                raise ValueError("Unsupported cache format; choose a new cache file")
            self._store = _json_value(payload["entries"])

    def get(self, row_key):
        if row_key not in self._store:
            return None
        value = self._store[row_key]
        return _FILTERED if value is None else copy.deepcopy(value)

    def set(self, row_key, output):
        self._store[row_key] = copy.deepcopy(_json_value(output))
        self._pending += 1
        if self._pending >= self.flush_every:
            self.flush()

    def flush(self):
        if not self._pending:
            return
        path = Path(self._path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_encoded({"format": 1, "entries": self._store}))
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
            self._pending = 0
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def to_DataTree(self):
        warnings.warn("Cache entries are not a saved run; use write_jsonl()", DeprecationWarning, stacklevel=2)
        from .DataTree import DataTree
        rows = [copy.deepcopy(v) for v in self._store.values() if v is not None]
        if not rows:
            raise ValueError("Cache has no non-filtered rows")
        return DataTree.from_records(rows)


class Program:
    """Immutable definition; expr() returns a new compiled program.

    Cache only deterministic row-local computations. cache_version is the
    caller's promise that callback code and all captured dependencies are stable.
    """
    __slots__ = ("__statements", "_name", "_cache", "_cache_version", "_plan", "_key", "_sealed")

    def __init__(self, cache=None, name=None, *, cache_version=None, _statements=()):
        if cache_version is not None and (not isinstance(cache_version, str) or not cache_version):
            raise ValueError("cache_version must be a non-empty string")
        object.__setattr__(self, "_sealed", False)
        self.__statements = tuple(copy.deepcopy(_flatten_stmts(_statements)))
        self._name, self._cache, self._cache_version = name, cache, cache_version
        self._plan = compile_plan(self.__statements)
        self._key = (_hash({"format": 1, "operations": _normalize(self.__statements, cache_version),
                            "version": cache_version}) if cache is not None else None)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("Program is immutable; expr() returns a new program")
        object.__setattr__(self, name, value)

    @property
    def _statements(self):
        return copy.deepcopy(self.__statements)

    def __repr__(self):
        return f"Program({self._name or '<auto>'!r}, {len(self.__statements)} stmts)"

    def _program_key(self):
        return self._key or _hash({"format": 1, "operations": _normalize(self.__statements, self._cache_version)})

    def expr(self, *statements):
        return Program(self._cache, self._name, cache_version=self._cache_version,
                       _statements=(*self.__statements, *_flatten_stmts(statements)))

    def __call__(self, dt):
        if self._cache is None:
            return self._plan.apply(dt)
        cache = self._cache
        def rows():
            try:
                for i, (record, meta) in enumerate(dt.scan()):
                    key = self._key + ":" + _hash(record.data)
                    hit = cache.get(key)
                    if hit is _FILTERED:
                        continue
                    if hit is None:
                        result = self._plan.execute(record, row=i)
                        output = result.data if result is not None else None
                        _json_value(output)
                        cache.set(key, copy.deepcopy(output))
                        if result is None:
                            continue
                    else:
                        output = hit
                    result = Record(copy.deepcopy(output), copy.deepcopy(meta))
                    yield result, result.meta
            finally:
                cache.flush()
        return dt._derive(rows)

    def to_DataTree(self):
        if self._cache is None:
            raise RuntimeError("No cache configured; use write_jsonl() to save output")
        return self._cache.to_DataTree()
