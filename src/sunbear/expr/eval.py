"""eval.py — per-record evaluator for Expr nodes.

Runs against a single Record — NO DataTree awareness.
"""
from __future__ import annotations

from .ast import (
    Expr, Lit, Col, BinOp, UnOp, Call, Placeholder,
)
# Handle PathBuilder from namespace.py at runtime to avoid circular import


# ═══════════════════════════════════════════════════════════════════════════
# OPS — arithmetic / comparison / boolean operators
# ═══════════════════════════════════════════════════════════════════════════

OPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "&": lambda a, b: a & b,
    "|": lambda a, b: a | b,
    "~": lambda a: not a,  # UnOp — invert boolean
}


# ═══════════════════════════════════════════════════════════════════════════
# FUNCS registry — populated by ops.py at import time
# ═══════════════════════════════════════════════════════════════════════════

FUNCS: dict = {}


def register_func(name: str, fn):
    """Register a runtime implementation for a value-tier op."""
    FUNCS[name] = fn


# ═══════════════════════════════════════════════════════════════════════════
# Evaluator
# ═══════════════════════════════════════════════════════════════════════════

def eval_value(node: Expr, record):
    """Evaluate an Expr node against a single Record.

    - Lit → node.value (returned unchanged)
    - Col / PathBuilder → record.get_leaves(node.indexer)
    - BinOp / UnOp → OPS[op](...)
    - Call → FUNCS[name](*eval(args), **eval(kwargs))
    - Placeholder → raises RuntimeError (should be substituted by chain)
    """
    if isinstance(node, Lit):
        return node.value
    if isinstance(node, Col):
        return record.get_leaves(node.indexer)
    # PathBuilder check by class name to avoid circular import
    if type(node).__name__ == "PathBuilder":
        return record.get_leaves(node.indexer)
    if isinstance(node, BinOp):
        return OPS[node.op](eval_value(node.left, record), eval_value(node.right, record))
    if isinstance(node, UnOp):
        return OPS[node.op](eval_value(node.operand, record))
    if isinstance(node, Call):
        return FUNCS[node.name](
            *[eval_value(a, record) for a in node.args],
            **{k: eval_value(v, record) for k, v in node.kwargs.items()}
        )
    if isinstance(node, Placeholder):
        raise RuntimeError("'_' placeholder used outside chain() — must be substituted at build time")
    raise TypeError(f"Unknown Expr node: {type(node).__name__}")


def eval_predicate(node: Expr, record) -> bool:
    """Evaluate a predicate expression against a record, coercing to bool."""
    return bool(eval_value(node, record))
