"""expr — declarative expression builder for DataTree.

Lower-level pieces (re-exported):
    b       — LazyNamespace, builds Path instances via attribute access
    _       — Placeholder for chain()
    Col     — explicit column reference (Sym-like)
    Lit, BinOp, UnOp, Call, Path, Placeholder — AST nodes

Statement builders (return tuples):
    assign(target, value)
    keep(pred)
    filter(target, pred)       — intra-record lazy filter
    map_field(target, fn)      — intra-record sbo.map
    flatten(target, level=-1)
    fork(cond, then_block, else_block)
    case(*clauses, default=())

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
    fork, case, run_expr,
)
from . import sbo

__all__ = [
    "Expr", "Lit", "Col", "BinOp", "UnOp", "Call", "Path", "Placeholder",
    "b", "_", "_wrap", "substitute", "compile", "OPS", "FUNCS", "register_func",
    "assign", "keep", "filter_field", "map_field", "flatten",
    "fork", "case", "run_expr",
    "sbo",
]
