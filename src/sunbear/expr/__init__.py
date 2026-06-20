"""sunbear expr — declarative expression builder API for SunBear DataTrees.

Usage:
    import sunbear as sb
    import numpy as np
    from sunbear.expr import b, assign, keep, Symbols

    age, height = Symbols("record.age", "record.height")
    mu = np.mean(dt.pluck(age))

    dt.expr(
        assign(b.normalized, (age - mu) / 2),
        keep(b.normalized < 50),
    )
"""

# AST nodes
from .ast import (
    Expr,
    Lit,
    Col,
    BinOp,
    UnOp,
    Call,
    # Statements
    Statement,
    Assign,
    Keep,
    Fork,
    Case,
    MapAssign,
    # Statement constructors
    assign,
    map_assign,
    keep,
    fork,
    case,
    # Placeholder
    _,
    # helpers
    _wrap,
)

# Namespace (symbolic references)
from .namespace import (
    Sym,
    Symbols,
    PathBuilder,
    LazyNamespace,
    b,
    as_indexer,
)

# Evaluator
from .eval import eval_value, eval_predicate, OPS, FUNCS

__all__ = [
    # AST
    "Expr",
    "Lit",
    "Col",
    "BinOp",
    "UnOp",
    "Call",
    # Statements
    "Statement",
    "Assign",
    "MapAssign",
    "Keep",
    "Fork",
    "Case",
    # Constructors
    "assign",
    "map_assign",
    "keep",
    "fork",
    "case",
    # Placeholder
    "_",
    "_wrap",
    # Namespace
    "Sym",
    "Symbols",
    "PathBuilder",
    "LazyNamespace",
    "b",
    "as_indexer",
    # Eval
    "eval_value",
    "eval_predicate",
    "OPS",
    "FUNCS",
]
