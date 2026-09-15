"""sbo.py — value-tier intra-record op builders (return Call nodes).

These produce Expr.Call nodes that are evaluated by FUNCS["flatten"|"filter"|"map"|"reduce"|"length"]
at compile-time / runtime.

Use inside an expr pipeline, e.g.::

    from sunbear.expr import b, assign, sbo

    dt.expr(
        assign(b.flat_tags, sbo.flatten(b.tags, -1)),
        assign(b.kept_tags, sbo.filter(b.flat_tags, lambda x: isinstance(x, str))),
    )
"""

from __future__ import annotations
from .ast import Call, Lit, _, Placeholder, substitute
from .eval import _MISSING


def flatten(value, level=-1) -> Call:
    """Flatten a nested list. ``level=-1`` (default) flattens fully."""
    return Call("flatten", [_wrap(value)], {"level": _wrap(level)})


def filter(value, pred) -> Call:
    """Intra-record filter. Lazy via metadata skip-flags.

    Returns a Call node; when evaluated, registers a skip mask in
    ``record.meta["_skips"]`` that the iterator consumer respects.
    """
    return Call("filter", [_wrap(value), _wrap(pred)])


def map(value, fn) -> Call:
    """Intra-record map. Returns a new list with ``fn(x)`` for each element."""
    return Call("map", [_wrap(value), _wrap(fn)])


def reduce(value, fn, init=_MISSING):
    """Intra-record reduce (fold over a list field).

    ``init`` is required if the list may be empty.
    """
    kwargs = {"fn": _wrap(fn), "init": _wrap(init)}
    return Call("reduce", [_wrap(value)], kwargs)


def length(value) -> Call:
    """Length of a list/string/collection field."""
    return Call("length", [_wrap(value)])


def size(value) -> Call:
    """Alias for length."""
    return length(value)


def count(value) -> Call:
    """Alias for length."""
    return length(value)


# ═══════════════════════════════════════════════════════════════════════════
# chain — build-time AST substitution pipeline
# ═══════════════════════════════════════════════════════════════════════════


def chain(seed, *steps):
    """Build-time AST substitution pipeline.

    First element must contain no ``_``; each subsequent element must
    contain ``_``. ``_`` is replaced with the accumulated expression.

    Example::

        chain(flatten(b.tags, -1), filter(_, lambda x: isinstance(x, str)))
    """
    acc = seed
    if _contains_placeholder(acc):
        raise ValueError("chain: first step must not contain '_'")
    for i, step in enumerate(steps):
        if not _contains_placeholder(step):
            raise ValueError(f"chain: step {i + 1} must contain '_'")
        acc = substitute(step, _, acc)
    return acc


def _contains_placeholder(node) -> bool:
    """Check whether an AST node contains a ``Placeholder`` reference."""
    if node is _:
        return True
    from .ast import Col, Path, BinOp, UnOp, Sugar, Item

    if isinstance(node, Sugar):
        return any(_contains_placeholder(a) for a in node.args)
    if isinstance(node, (Lit, Col, Path, Placeholder, Item)):
        return False
    if isinstance(node, BinOp):
        return _contains_placeholder(node.left) or _contains_placeholder(node.right)
    if isinstance(node, UnOp):
        return _contains_placeholder(node.operand)
    if isinstance(node, Call):
        return any(_contains_placeholder(a) for a in node.args) or any(
            _contains_placeholder(v) for v in node.kwargs.values()
        )
    return False


def _wrap(x):
    """Local _wrap (also exported from ast.py). Coerce value to Expr."""
    from .ast import Expr as _Expr, Lit as _Lit

    if isinstance(x, _Expr):
        return x
    return _Lit(x)
