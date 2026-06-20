"""ops.py — value-tier expr ops (sbo: flatten, filter, map, reduce, chain).

Each builder returns a ``Call`` node. Runtime implementations are registered
in ``eval.FUNCS`` at import time.
"""
from __future__ import annotations

from .expr.ast import Lit, Call, substitute, _wrap, Expr, _
from .expr.eval import register_func

_MISSING = object()  # sentinel for reduce init default


# ═══════════════════════════════════════════════════════════════════════════
# sbo value-tier builders
# ═══════════════════════════════════════════════════════════════════════════

def flatten(value, level=-1) -> Call:
    """sbo.flatten: Flatten a nested list structure.

    Args:
        value: The value/list to flatten.
        level: How many levels to flatten. -1 means fully flatten.
    """
    return Call("flatten", [_wrap(value)], {"level": _wrap(level)})


def filter(value, pred) -> Call:
    """sbo.filter: Within-field filter, not record-level.

    Args:
        value: A list value.
        pred: A lambda/predicate applied to each element.
    """
    return Call("filter", [_wrap(value), _wrap(pred)])


def map(value, fn) -> Call:
    """sbo.map: Within-field map.

    Args:
        value: A list value.
        fn: A lambda applied to each element.
    """
    return Call("map", [_wrap(value), _wrap(fn)])


def reduce(value, fn, init=_MISSING) -> Call:
    """sbo.reduce: Within-field reduction.

    Args:
        value: A list value.
        fn: Binary reduction function.
        init: Initial value (optional). If omitted and list is empty, raises.
    """
    kwargs = {"fn": _wrap(fn)}
    if init is not _MISSING:
        kwargs["init"] = _wrap(init)
    return Call("reduce", [_wrap(value)], kwargs)


def length(value) -> Call:
    """sbo.length: Length of a list/string field.

    Wraps ``len(value)`` as a value-tier Call. Use this when you want to
    filter by the size of a field — e.g.:

        keep(sbo.length(b.tags) > 0)

    Args:
        value: A list, string, or other sized value.
    """
    return Call("length", [_wrap(value)])


def size(value) -> Call:
    """Alias for ``sbo.length``."""
    return length(value)


def count(value) -> Call:
    """Alias for ``sbo.length`` (semantic preference for some users)."""
    return length(value)


# ═══════════════════════════════════════════════════════════════════════════
# chain / _ — build-time AST substitution
# ═══════════════════════════════════════════════════════════════════════════

def chain(seed, *steps) -> Expr:
    """Build-time AST substitution pipeline.

    First element must contain no ``_``; each subsequent element must
    contain ``_``.  ``_`` is replaced with the accumulated expression.

    Example:
        chain(flatten(b.tags, -1), filter(_, lambda x: isinstance(x, str)))
    """
    # `Placeholder` is a class, `_` is the singleton instance. We must use
    # the instance for identity-based substitution/matching.

    acc = _wrap(seed)

    # Validate: seed must not contain _
    if _contains(acc, _):
        raise ValueError("chain() seed must not contain '_' placeholder")

    for i, step in enumerate(steps):
        if not _contains(step, _):
            raise ValueError(
                f"chain() step {i + 1} must contain '_' placeholder"
            )
        acc = substitute(_wrap(step), _, acc)

    return acc


def _contains(node, token) -> bool:
    """Check if token appears anywhere in the AST."""
    if node is token:
        return True
    from .expr.ast import Lit, Col, BinOp, UnOp, Call
    if isinstance(node, (Lit, Col)):
        return False
    if type(node).__name__ == "PathBuilder":
        return False
    if isinstance(node, BinOp):
        return _contains(node.left, token) or _contains(node.right, token)
    if isinstance(node, UnOp):
        return _contains(node.operand, token)
    if isinstance(node, Call):
        for a in node.args:
            if _contains(a, token):
                return True
        for v in node.kwargs.values():
            if _contains(v, token):
                return True
        return False
    return False


# ═══════════════════════════════════════════════════════════════════════════
# Runtime implementations — registered into eval.FUNCS
# ═══════════════════════════════════════════════════════════════════════════

def _runtime_flatten(value, level=-1):
    """Recursively flatten a list to the given level.

    level=-1 means flatten completely until no sublists remain.
    level=0 means no flattening.  level=1 flattens one level, etc.
    """
    def _flatten(v, current_level):
        if not isinstance(v, (list, tuple)):
            return [v]
        if level >= 0 and current_level >= level:
            return [v]
        result = []
        for item in v:
            result.extend(_flatten(item, current_level + 1))
        return result
    return _flatten(value, 0)


def _runtime_filter(value, pred):
    """Filter elements of a list."""
    if not isinstance(value, (list, tuple)):
        return []
    return [x for x in value if pred(x)]


def _runtime_map(value, fn):
    """Map a function over list elements."""
    if not isinstance(value, (list, tuple)):
        return []
    return [fn(x) for x in value]


def _runtime_reduce(value, fn, init=_MISSING):
    """Reduce a list with a binary function."""
    from functools import reduce as _functools_reduce
    if not isinstance(value, (list, tuple)):
        if init is not _MISSING:
            return init
        raise TypeError("reduce() of empty sequence with no initial value")
    if len(value) == 0:
        if init is not _MISSING:
            return init
        raise TypeError("reduce() of empty sequence with no initial value")
    if init is not _MISSING:
        return _functools_reduce(fn, value, init)
    return _functools_reduce(fn, value)


def _runtime_length(value):
    """Length of a list/string/dict value. None → 0."""
    if value is None:
        return 0
    try:
        return len(value)
    except TypeError:
        return 0


# Auto-register at import time
register_func("flatten", _runtime_flatten)
register_func("filter", _runtime_filter)
register_func("map", _runtime_map)
register_func("reduce", _runtime_reduce)
register_func("length", _runtime_length)
