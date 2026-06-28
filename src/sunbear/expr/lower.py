"""lower.py — lower expr statements (tuples) to DataTree operations.

Statements are tuples:
  ("assign", path, expr)         → dt.assign_at(path, compile(expr))
  ("keep", pred)                 → dt.filter(lambda r, m: bool(compile(pred)(r)))
  ("filter", path, pred_expr)    → intra-record lazy filter via sbo.filter
  ("map", path, fn_expr)         → intra-record sbo.map
  ("flatten", path, level)       → intra-record sbo.flatten
  ("fork", cond, then_stmts, else_stmts) → dt.apply(branch_fn)
  ("case", clauses, default)     → dt.apply(case_fn)
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from .ast import Expr, _wrap, Call, Lit
from .eval import compile


# ═══════════════════════════════════════════════════════════════════════════
# Statement constructors (return tuples)
# ═══════════════════════════════════════════════════════════════════════════

def assign(target, value):
    return ("assign", _wrap(target), _wrap(value))


def keep(pred):
    return ("keep", _wrap(pred))


def filter_field(target, pred):
    """Intra-record filter. Lazy via metadata skip-flags."""
    return ("filter", _wrap(target), _wrap(pred))


def map_field(target, fn):
    return ("map", _wrap(target), _wrap(fn))


def flatten(target, level=-1):
    return ("flatten", _wrap(target), Lit(level))


def fork(cond, then_block=(), else_block=()):
    return ("fork", _wrap(cond), tuple(then_block), tuple(else_block))


def case(*clauses, default=()):
    return ("case", tuple((_wrap(c), tuple(b)) for c, b in clauses), tuple(default))


def map_assign(target, source, fn, *args, **kwargs):
    """Map fn over per-row source value, write to target. Equivalent to
    ``assign(target, sbo.map(source, fn, *args, **kwargs))``.
    """
    from .sbo import map as sbo_map
    return ("assign", _wrap(target), sbo_map(source, fn, *args, **kwargs))


# ═══════════════════════════════════════════════════════════════════════════
# Lower a single statement to a DataTree method call
# ═══════════════════════════════════════════════════════════════════════════

def _lower(stmt, dt):
    kind = stmt[0]

    if kind == "assign":
        _, path, value = stmt
        return dt.assign_at(path, _fn_for(value))

    if kind == "keep":
        _, pred = stmt
        f = compile(pred)
        return dt.filter(lambda r, m, _f=f: bool(_f(r)))

    if kind == "filter":
        # intra-record: just call the value (filter registers skip in meta)
        path, pred = stmt[1], stmt[2]
        f_pred = compile(pred)
        def _row_fn(r, _f=f_pred, _p=path):
            cur = r.get(_p)
            from .eval import FUNCS, _MISSING
            return FUNCS["filter"](cur, _f, r)
        return dt.assign_at(path, _row_fn)

    if kind == "map":
        path, fn = stmt[1], stmt[2]
        f_fn = compile(fn)
        def _row_fn(r, _f=f_fn, _p=path):
            from .eval import FUNCS
            return FUNCS["map"](r.get(_p), _f)
        return dt.assign_at(path, _row_fn)

    if kind == "flatten":
        path, level = stmt[1], stmt[2]
        f_level = compile(level)
        def _row_fn(r, _f=f_level, _p=path):
            from .eval import FUNCS
            return FUNCS["flatten"](r.get(_p), _f(r))
        return dt.assign_at(path, _row_fn)

    if kind == "fork":
        _, cond, then_block, else_block = stmt
        f_cond = compile(cond)
        # Build per-row branch fn that produces a new record.
        from ..Record import Record
        def _row_fn(r):
            nr = Record(dict(r.data), dict(r.meta))
            block = then_block if bool(f_cond(r)) else else_block
            for s in block:
                _apply_to_record(nr, s)
            return nr
        return dt.apply(_row_fn)

    if kind == "case":
        _, clauses, default = stmt
        compiled = [(compile(c), b) for c, b in clauses]
        from ..Record import Record
        def _row_fn(r):
            nr = Record(dict(r.data), dict(r.meta))
            for f_cond, block in compiled:
                if bool(f_cond(r)):
                    for s in block:
                        _apply_to_record(nr, s)
                    return nr
            for s in default:
                _apply_to_record(nr, s)
            return nr
        return dt.apply(_row_fn)

    raise TypeError(f"Unknown statement kind: {kind!r}")


def _fn_for(expr):
    """Compile an expression to a (record) → value closure."""
    return compile(expr)


def _apply_to_record(r, stmt):
    """Apply a statement directly to a record (used by fork/case branch fns)."""
    kind = stmt[0]
    if kind == "assign":
        _, path, value = stmt
        r.set(path, compile(value)(r))
        return
    if kind == "filter":
        from .eval import FUNCS
        path, pred = stmt[1], stmt[2]
        f_pred = compile(pred)
        new = FUNCS["filter"](r.get(path), f_pred, r)
        r.set(path, new)
        return
    if kind == "map":
        from .eval import FUNCS
        path, fn = stmt[1], stmt[2]
        f_fn = compile(fn)
        r.set(path, FUNCS["map"](r.get(path), f_fn))
        return
    if kind == "flatten":
        from .eval import FUNCS
        path, level = stmt[1], stmt[2]
        f_level = compile(level)
        r.set(path, FUNCS["flatten"](r.get(path), f_level(r)))
        return
    raise TypeError(f"Cannot apply statement {kind!r} directly to a record")


# ═══════════════════════════════════════════════════════════════════════════
# Public entry: run a sequence of expr statements against a DataTree
# ═══════════════════════════════════════════════════════════════════════════

def run_expr(dt, *statements):
    """Apply a sequence of expr statements to a DataTree.

    Statements are tuples returned by ``assign()``, ``keep()``, etc.
    Nested lists/tuples are flattened. Applied eagerly in order.
    """
    flat = _flatten_stmts(statements)
    for stmt in flat:
        if not (isinstance(stmt, tuple) and stmt and isinstance(stmt[0], str)):
            raise TypeError(f"Expected a tuple statement, got: {stmt!r}")
        dt = _lower(stmt, dt)
    return dt


def _flatten_stmts(items):
    """Flatten nested lists/tuples of statements, keeping statement tuples intact."""
    out = []
    for item in items:
        if isinstance(item, (list, tuple)) and item and isinstance(item[0], str) \
                and item[0] in {"assign", "keep", "filter", "map", "flatten",
                                "fork", "case"}:
            out.append(item)
        elif isinstance(item, (list, tuple)):
            out.extend(_flatten_stmts(item))
        else:
            out.append(item)
    return out
