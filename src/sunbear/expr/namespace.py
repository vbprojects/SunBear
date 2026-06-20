"""namespace.py — symbolic sugar for building path references to record fields.

- ``Sym("record.age")`` → ``Col("record.age")``
- ``Symbols("a", "b")`` → ``(Col("a"), Col("b"))``
- ``b.record.age`` → ``PathBuilder("record.age")``
- ``as_indexer(x)`` → extract indexer for DataTree methods
"""
from __future__ import annotations

from .ast import Expr, Col


# ═══════════════════════════════════════════════════════════════════════════
# Sym / Symbols — explicit leaf references
# ═══════════════════════════════════════════════════════════════════════════

def Sym(name: str) -> Col:
    """Create a column reference: ``Sym("record.age")`` → ``Col("record.age")``."""
    return Col(name)


def Symbols(*names: str) -> tuple[Col, ...]:
    """Create multiple column references: ``Symbols("a", "b", "c")``."""
    return tuple(Col(n) for n in names)


# ═══════════════════════════════════════════════════════════════════════════
# PathBuilder — lazy attribute-access path builder
# ═══════════════════════════════════════════════════════════════════════════

class PathBuilder(Expr):
    """Lazy path reference built via attribute access: ``b.record.age``.

    Keep method-free (no non-dunder public methods) so attribute access
    is unambiguously path-building. Use ``b["alias"]`` for fields that
    collide with dunder/attr names.
    """

    __slots__ = ("indexer",)

    def __init__(self, indexer: str):
        self.indexer = indexer

    def __repr__(self):
        return f"PathBuilder({self.indexer!r})"

    # -- path extension --------------------------------------------------
    def __getattr__(self, nxt: str) -> "PathBuilder":
        # Allow private attrs for dunder protocol (__slots__, etc.) to fall through
        if nxt.startswith("_"):
            raise AttributeError(nxt)
        return PathBuilder(f"{self.indexer}.{nxt}")

    def __getitem__(self, key) -> "PathBuilder":
        """Fallback for non-identifier fields: ``b["x y"]`` or ``b[0]``."""
        if isinstance(key, str):
            return PathBuilder(f"{self.indexer}.{key}")
        return PathBuilder(f"{self.indexer}[{key}]")

    # PathBuilder is a leaf-like Expr — evaluated as record.get_leaves(indexer)


# ═══════════════════════════════════════════════════════════════════════════
# LazyNamespace — the ``b`` singleton
# ═══════════════════════════════════════════════════════════════════════════

class LazyNamespace:
    """Entry point for lazy attribute-access path building.

    Usage:

        from sunbear.expr import b
        b.record.age      # → PathBuilder("record.age")
        b["x y"]          # → PathBuilder("x y")
    """

    def __getattr__(self, name: str) -> PathBuilder:
        if name.startswith("_"):
            raise AttributeError(name)
        return PathBuilder(name)

    def __getitem__(self, key) -> PathBuilder:
        """``b["alias"]`` — for fields colliding with dunder or reserved names."""
        if isinstance(key, str):
            return PathBuilder(key)
        return PathBuilder(str(key))


# Singleton — exported as `b`
b = LazyNamespace()


# ═══════════════════════════════════════════════════════════════════════════
# as_indexer — normalize Col/PathBuilder to plain indexer for DataTree
# ═══════════════════════════════════════════════════════════════════════════

def as_indexer(x):
    """Return ``x.indexer`` if x is an Expr leaf (Col / PathBuilder), else x unchanged.

    This allows DataTree methods (pluck, col, select, group_by, sort_by)
    to accept Symbols/PathBuilders transparently.
    """
    if isinstance(x, Col):
        return x.indexer
    if isinstance(x, PathBuilder):
        return x.indexer
    # Could be plain str, tuple, list — pass through
    return x
