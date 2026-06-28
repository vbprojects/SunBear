"""ast.py — Expr nodes, Path, Placeholder, _wrap.

Minimal AST: 4 value-tier nodes (Lit, Col, BinOp, Call), no Statement classes.
Statements are tuples — see lower.py.
"""
from __future__ import annotations
from typing import Any


# ═══════════════════════════════════════════════════════════════════════════
# _wrap: coerce any value to an Expr
# ═══════════════════════════════════════════════════════════════════════════

def _wrap(x):
    """Return x unchanged if Expr, else wrap in Lit."""
    if isinstance(x, Expr):
        return x
    return Lit(x)


# ═══════════════════════════════════════════════════════════════════════════
# Expr base class
# ═══════════════════════════════════════════════════════════════════════════

class Expr:
    """Base for all expression nodes. Operator overloading composes BinOp/UnOp."""

    __hash__ = None

    # arithmetic
    def __add__(self, other):  return BinOp("+", self, _wrap(other))
    def __radd__(self, other): return BinOp("+", _wrap(other), self)
    def __sub__(self, other):  return BinOp("-", self, _wrap(other))
    def __rsub__(self, other): return BinOp("-", _wrap(other), self)
    def __mul__(self, other):  return BinOp("*", self, _wrap(other))
    def __rmul__(self, other): return BinOp("*", _wrap(other), self)
    def __truediv__(self, other):  return BinOp("/", self, _wrap(other))
    def __rtruediv__(self, other): return BinOp("/", _wrap(other), self)

    # comparison
    def __lt__(self, other): return BinOp("<",  self, _wrap(other))
    def __le__(self, other): return BinOp("<=", self, _wrap(other))
    def __gt__(self, other): return BinOp(">",  self, _wrap(other))
    def __ge__(self, other): return BinOp(">=", self, _wrap(other))
    def __eq__(self, other): return BinOp("==", self, _wrap(other))
    def __ne__(self, other): return BinOp("!=", self, _wrap(other))

    # boolean
    def __and__(self, other): return BinOp("&", self, _wrap(other))
    def __or__(self, other):  return BinOp("|", self, _wrap(other))
    def __invert__(self):     return UnOp("~", self)


# ═══════════════════════════════════════════════════════════════════════════
# Value-tier nodes
# ═══════════════════════════════════════════════════════════════════════════

class Lit(Expr):
    """Literal value (numbers, lambdas, level= ints, etc.)."""
    __slots__ = ("value",)
    def __init__(self, value): self.value = value
    def __repr__(self): return f"Lit({self.value!r})"


class Col(Expr):
    """Leaf reference to a record path (string indexer)."""
    __slots__ = ("indexer",)
    def __init__(self, indexer: str): self.indexer = indexer
    def __repr__(self): return f"Col({self.indexer!r})"


class BinOp(Expr):
    """Binary op: ``op(left, right)``."""
    __slots__ = ("op", "left", "right")
    def __init__(self, op: str, left: Expr, right: Expr):
        self.op, self.left, self.right = op, left, right
    def __repr__(self): return f"BinOp({self.op!r}, {self.left!r}, {self.right!r})"


class UnOp(Expr):
    """Unary op: ``op(operand)``."""
    __slots__ = ("op", "operand")
    def __init__(self, op: str, operand: Expr):
        self.op, self.operand = op, operand
    def __repr__(self): return f"UnOp({self.op!r}, {self.operand!r})"


class Call(Expr):
    """Value-tier op: ``FUNCS[name](*args, **kwargs)``."""
    __slots__ = ("name", "args", "kwargs")
    def __init__(self, name: str, args=(), kwargs=None):
        self.name = name
        self.args = tuple(args)
        self.kwargs = dict(kwargs) if kwargs else {}
    def __repr__(self): return f"Call({self.name!r}, args={self.args!r}, kwargs={self.kwargs!r})"


# ═══════════════════════════════════════════════════════════════════════════
# Path — lazy attribute-access path builder (single class, replaces both
# PathBuilder and LazyNamespace from the old codebase)
# ═══════════════════════════════════════════════════════════════════════════

class Path(Expr):
    """Lazy path reference built via attribute access: ``b.record.age``.

    ``Path("a.b")`` is equivalent to ``Col("a.b")`` at evaluation time.
    """

    __slots__ = ("indexer",)

    def __init__(self, indexer: str):
        self.indexer = indexer

    def __repr__(self):
        return f"Path({self.indexer!r})"

    def __getattr__(self, nxt: str) -> "Path":
        if nxt.startswith("_"):
            raise AttributeError(nxt)
        return Path(f"{self.indexer}.{nxt}" if self.indexer else nxt)

    def __getitem__(self, key) -> "Path":
        if isinstance(key, str):
            return Path(f"{self.indexer}.{key}" if self.indexer else key)
        return Path(f"{self.indexer}[{key}]" if self.indexer else str(key))


# ═══════════════════════════════════════════════════════════════════════════
# LazyNamespace — ``b`` entry point (small wrapper, returns Path instances)
# ═══════════════════════════════════════════════════════════════════════════

class LazyNamespace:
    """``b.a.b.c`` → ``Path("a.b.c")``."""

    indexer = ""

    def __getattr__(self, name: str) -> Path:
        if name.startswith("_"):
            raise AttributeError(name)
        return Path(name)

    def __getitem__(self, key) -> Path:
        if isinstance(key, str):
            return Path(key)
        return Path(str(key))


b = LazyNamespace()


# ═══════════════════════════════════════════════════════════════════════════
# Placeholder — ``_`` singleton for chain()
# ═══════════════════════════════════════════════════════════════════════════

class Placeholder(Expr):
    """The ``_`` token used inside chain(). Substituted away at build time."""

    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self): return "_"


_ = Placeholder()


# ═══════════════════════════════════════════════════════════════════════════
# substitute — deep AST walk (used by chain())
# ═══════════════════════════════════════════════════════════════════════════

def substitute(node, token, replacement):
    """Replace every occurrence of ``token`` with ``replacement``."""
    if node is token:
        return replacement
    if isinstance(node, (Lit, Col, Path, Placeholder)):
        return node
    if isinstance(node, BinOp):
        return BinOp(node.op,
                     substitute(node.left, token, replacement),
                     substitute(node.right, token, replacement))
    if isinstance(node, UnOp):
        return UnOp(node.op, substitute(node.operand, token, replacement))
    if isinstance(node, Call):
        return Call(
            node.name,
            [substitute(a, token, replacement) for a in node.args],
            {k: substitute(v, token, replacement) for k, v in node.kwargs.items()},
        )
    return node
