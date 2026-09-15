"""eval.py — compile AST to per-record closure + intra-record ops registry.

Two halves:
1. compile(node) → (record) → value. Pure AST walker, no DataTree awareness.
2. FUNCS registry for value-tier ops (sbo.flatten/filter/map/reduce/length).
   `sbo.filter` uses the metadata skip-flag mechanism for lazy iteration.
"""
from __future__ import annotations
from typing import Any, Callable

from ..paths import MISSING
from .ast import Expr, Lit, Col, BinOp, UnOp, Call, Path, Placeholder


# ═══════════════════════════════════════════════════════════════════════════
# OPS — arithmetic / comparison / boolean operators
# ═══════════════════════════════════════════════════════════════════════════

OPS = {
    "+":  lambda a, b: a + b,
    "-":  lambda a, b: a - b,
    "*":  lambda a, b: a * b,
    "/":  lambda a, b: a / b,
    "<":  lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">":  lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "&":  lambda a, b: bool(a) and bool(b),
    "|":  lambda a, b: bool(a) or bool(b),
    "~":  lambda a: not a,
}


# ═══════════════════════════════════════════════════════════════════════════
# FUNCS registry — populated by intra-record ops (below)
# ═══════════════════════════════════════════════════════════════════════════

FUNCS: dict = {}


def register_func(name: str, fn: Callable) -> None:
    """Register a runtime implementation for a value-tier op."""
    FUNCS[name] = fn


# ═══════════════════════════════════════════════════════════════════════════
# compile — AST → (record) → value
# ═══════════════════════════════════════════════════════════════════════════

def compile(node: Expr):
    """Compile an Expr node to a closure ``(record) → value``.

    Path binding lives in Col/Path: ``r.get(node.indexer)``.
    """
    if isinstance(node, Lit):
        v = node.value
        return lambda r: v
    if isinstance(node, Col):
        ix = node.indexer
        return lambda r: r.get(ix, MISSING)
    if isinstance(node, Path):
        ix = node.indexer
        return lambda r: r.get(ix, MISSING)
    if isinstance(node, BinOp):
        L = compile(node.left)
        R = compile(node.right)
        op = OPS[node.op]
        if node.op == "&":
            return lambda r: bool(L(r)) and bool(R(r))
        if node.op == "|":
            return lambda r: bool(L(r)) or bool(R(r))
        return lambda r: op(L(r), R(r))
    if isinstance(node, UnOp):
        operand = compile(node.operand)
        op = OPS[node.op]
        return lambda r: op(operand(r))
    if isinstance(node, Call):
        implementation = FUNCS[node.name]
        A = [compile(a) for a in node.args]
        K = {k: compile(v) for k, v in node.kwargs.items()}
        # Ops that need the record itself (for metadata side-effects).
        # They receive (value..., record) as trailing positional arg.
        _RECORD_AWARE = {"filter"}
        if node.name in _RECORD_AWARE:
            def closure(r, _A=A, _K=K, _name=node.name):
                return implementation(
                    *[a(r) for a in _A],
                    r,
                    **{k: v(r) for k, v in _K.items()},
                )
            return closure
        def closure(r, _A=A, _K=K, _name=node.name):
            return implementation(
                *[a(r) for a in _A],
                **{k: v(r) for k, v in _K.items()},
            )
        return closure
    if isinstance(node, Placeholder):
        raise RuntimeError("'_' placeholder used outside chain() — must be substituted at build time")
    raise TypeError(f"Unknown Expr node: {type(node).__name__}")


# ═══════════════════════════════════════════════════════════════════════════
# Intra-record ops (sbo.*) — operate on values within a single record
# ═══════════════════════════════════════════════════════════════════════════

_MISSING = MISSING


def _coerce_list(v):
    if isinstance(v, list):
        return v
    if v is None or v is _MISSING:
        return []
    return list(v)


def _flatten_value(v, level):
    """Flatten a nested list structure.

    level=-1 (default) flattens fully. level=N flattens N levels deep.
    """
    items = _coerce_list(v)
    if level == 0:
        return list(items)
    out = []
    for x in items:
        if isinstance(x, list):
            if level < 0:
                out.extend(_flatten_value(x, -1))
            else:
                out.extend(_flatten_value(x, level - 1))
        else:
            out.append(x)
    return out


def _filter_value(v, pred, record):
    """LAZY FILTER — writes a skip mask into record.meta; returns the kept items.

    The DataTree scan loop consumes the mask during iteration to filter out
    skipped elements WITHOUT having to materialize the skip list eagerly.
    """
    items = _coerce_list(v)
    skip_mask = []
    kept = []
    for item in items:
        keep = bool(pred(item))
        skip_mask.append(not keep)
        if keep:
            kept.append(item)
    if any(skip_mask):
        record.meta.setdefault("_skips", {})[id(record)] = skip_mask
    return kept


def _map_value(v, fn):
    items = _coerce_list(v)
    return [fn(x) for x in items]


def _reduce_value(v, fn, init):
    items = _coerce_list(v)
    if not items:
        if init is _MISSING:
            raise ValueError("sbo.reduce of empty list with no init")
        return init
    acc = items[0] if init is _MISSING else init
    it = items[1:] if init is _MISSING else items
    for x in it:
        acc = fn(acc, x)
    return acc


def _length_value(v):
    if v is None or v is _MISSING:
        return 0
    return len(v)


# Register at import time
register_func("flatten", _flatten_value)
register_func("filter", _filter_value)
register_func("map", _map_value)
register_func("reduce", _reduce_value)
register_func("length", _length_value)
register_func("size", _length_value)
register_func("count", _length_value)

# Sugar ops used by cast/upper/lower/trim/round_field
register_func("__upper", lambda v: v.upper() if isinstance(v, str) else v)
register_func("__lower", lambda v: v.lower() if isinstance(v, str) else v)
register_func("__trim", lambda v: v.strip() if isinstance(v, str) else v)
register_func("__round", lambda v, ndigits=0: round(v, ndigits))
register_func("__cast", lambda v, type=None: type(v) if type is not None else v)

register_func("exists", lambda v: v is not MISSING)
register_func("is_null", lambda v: v is None)
register_func("is_not_null", lambda v: v is not None and v is not MISSING)
register_func("fill_missing", lambda v, default: default if v is MISSING else v)

BUILTIN_FUNCS = dict(FUNCS)
