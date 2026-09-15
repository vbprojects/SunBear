"""Immutable compiled programs, explicit memoization, and strict JSON caches."""

from __future__ import annotations

import copy
from .record import Record
from .paths import MISSING, PathSpec
from .expr.ast import Expr, Lit, Path as ExprPath, Col, BinOp, UnOp, Call, Sugar, Item
from .expr.lower import compile_plan, _flatten_stmts

from .cache import AbstractCache, FileCache, _FILTERED
from ._codec import _json_value, _encoded, _hash


def _normalize(value, version):
    from .selectors import Selector

    if isinstance(value, Selector):
        return {"selector": [value.kind, _normalize(value.args, version)]}
    if isinstance(value, Sugar):
        return {
            "sugar": [
                value.kind,
                _normalize(value.args, version),
                _normalize(value.options, version),
            ]
        }
    if isinstance(value, Item):
        return {"item": [value.symbol, _normalize(value.indexer, version)]}
    if value is MISSING:
        return {"missing": True}
    if isinstance(value, PathSpec):
        return {
            "path": [
                [type(s).__name__, getattr(s, "value", None)] for s in value.segments
            ]
        }
    if isinstance(value, (ExprPath, Col)):
        ix = value.indexer
        return _normalize(PathSpec.dotted(ix) if isinstance(ix, str) else ix, version)
    if isinstance(value, Lit):
        return {"literal": _normalize(value.value, version)}
    if isinstance(value, BinOp):
        return {
            "binary": [
                value.op,
                _normalize(value.left, version),
                _normalize(value.right, version),
            ]
        }
    if isinstance(value, UnOp):
        return {"unary": [value.op, _normalize(value.operand, version)]}
    if isinstance(value, Call):
        from .expr.eval import FUNCS, BUILTIN_FUNCS

        if FUNCS.get(value.name) is not BUILTIN_FUNCS.get(value.name) and not version:
            raise ValueError(
                "Caching custom registered functions requires cache_version"
            )
        return {
            "call": [
                value.name,
                _normalize(value.args, version),
                _normalize(value.kwargs, version),
            ]
        }
    if callable(value):
        if not version:
            raise ValueError("Caching callbacks requires an explicit cache_version")
        return {
            "callback": [
                getattr(value, "__module__", ""),
                getattr(value, "__qualname__", type(value).__qualname__),
                version,
            ]
        }
    if isinstance(value, tuple):
        return {"tuple": [_normalize(v, version) for v in value]}
    if isinstance(value, list):
        return [_normalize(v, version) for v in value]
    if isinstance(value, dict):
        return {k: _normalize(v, version) for k, v in value.items()}
    return _json_value(value)


from ._fluent import Fluent


class Program(Fluent):
    """Immutable definition; expr() returns a new compiled program.

    Cache only deterministic row-local computations. cache_version is the
    caller's promise that callback code and all captured dependencies are stable.
    """

    __slots__ = (
        "__statements",
        "_name",
        "_cache",
        "_cache_version",
        "_plan",
        "_key",
        "_sealed",
    )

    def __init__(self, cache=None, name=None, *, cache_version=None, _statements=()):
        if cache_version is not None and (
            not isinstance(cache_version, str) or not cache_version
        ):
            raise ValueError("cache_version must be a non-empty string")
        object.__setattr__(self, "_sealed", False)
        self.__statements = tuple(copy.deepcopy(_flatten_stmts(_statements)))
        self._name, self._cache, self._cache_version = name, cache, cache_version
        self._plan = compile_plan(self.__statements)
        self._key = (
            _hash(
                {
                    "format": 1,
                    "operations": _normalize(self.__statements, cache_version),
                    "version": cache_version,
                }
            )
            if cache is not None
            else None
        )
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
        return self._key or _hash(
            {
                "format": 1,
                "operations": _normalize(self.__statements, self._cache_version),
            }
        )

    def expr(self, *statements):
        return Program(
            self._cache,
            self._name,
            cache_version=self._cache_version,
            _statements=(*self.__statements, *_flatten_stmts(statements)),
        )

    def then(self, other):
        if not isinstance(other, Program):
            raise TypeError("then requires a Program")
        return self.expr(*other._statements)

    def _execute_record(self, record, row=None):
        if self._cache is None:
            return self._plan.execute(record, row=row)
        key = self._key + ":" + _hash(record.data)
        hit = self._cache.get(key)
        if hit is _FILTERED:
            return None
        if hit is None:
            result = self._plan.execute(record, row=row)
            output = result.data if result is not None else None
            _json_value(output)
            self._cache.set(key, copy.deepcopy(output))
            if result is None:
                return None
        else:
            output = hit
        return Record(copy.deepcopy(output), copy.deepcopy(record.meta))

    def __call__(self, dt):
        if self._cache is None:
            return self._plan.apply(dt)

        def rows():
            try:
                for i, (record, meta) in enumerate(dt.scan()):
                    result = self._execute_record(record, row=i)
                    if result is not None:
                        yield result, result.meta
            finally:
                self._cache.flush()

        return dt._derive(rows)

    def to_DataTree(self):
        if self._cache is None:
            raise RuntimeError("No cache configured; use write_jsonl() to save output")
        return self._cache.to_DataTree()
