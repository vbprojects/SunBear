"""expr — declarative expression builder for DataTree.

Lower-level pieces (re-exported):
    b       — LazyNamespace, builds Path instances via attribute access
    _       — Placeholder for chain()
    Col     — explicit column reference (Sym-like)
    Lit, BinOp, UnOp, Call, Path, Placeholder — AST nodes

Statement builders (return tuples):
    assign(target, value)       — positional form
    assign(key=value, ...)      — keyword sugar (key is target path)
    keep(pred)
    filter(target, pred)        — intra-record lazy filter
    map_field(target, fn)       — intra-record sbo.map
    flatten(target, level=-1)
    fork(cond, then_block, else_block)
    case(*clauses, default=())
    select(*args, **kwargs)     — project/rename, drop unselected fields

Structural ops (1→1 shape):
    rename(**mapping)           — move fields (old_name="new_name")
    drop(*paths)                — remove fields
    copy_field(src, dst)        — duplicate a field
    default(target, value)      — set field only if None
    nest(*paths, into=)         — group fields into a nested dict
    unnest(path)                — flatten nested dict into top-level

Conditional ops (1→{0,1}):
    assert_(pred, message=None) — filter/raise on failing rows
    mask(target, pred, value)   — set field only where pred holds

Sugar ops:
    cast(target, type_)         — type coercion
    upper(target)               — uppercase string field
    lower_str(target)           — lowercase string field
    trim(target)                — strip whitespace
    round_field(target, ndigits) — round numeric field
    coalesce(*paths, target=)   — first non-None value

Path sugar:
    b.x |= expr                 — equivalent to assign(b.x, expr)

Runtime (sbo namespace):
    sbo.flatten(value, level=-1)
    sbo.filter(value, pred)     — value-tier lazy filter (uses meta skip-flags)
    sbo.map(value, fn)
    sbo.reduce(value, fn, init=_MISSING)
    sbo.length(value)
"""
from .ast import (
    Expr, Lit, Col, BinOp, UnOp, Call, Path, Placeholder, b, _,
    _wrap, substitute,
)
from .eval import compile, OPS, FUNCS, register_func
from .lower import (
    assign, keep, filter_field, map_field, flatten,
    fork, case, select, run_expr,
    rename, drop, copy_field, default, nest, unnest,
    assert_, mask, cast, upper, lower_str, trim, round_field, coalesce,
)
from . import sbo

__all__ = [
    "Expr", "Lit", "Col", "BinOp", "UnOp", "Call", "Path", "Placeholder",
    "b", "_", "_wrap", "substitute", "compile", "OPS", "FUNCS", "register_func",
    "assign", "keep", "filter_field", "map_field", "flatten",
    "fork", "case", "select", "run_expr",
    "rename", "drop", "copy_field", "default", "nest", "unnest",
    "assert_", "mask", "cast", "upper", "lower_str", "trim", "round_field", "coalesce",
    "sbo",
]
