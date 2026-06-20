"""ast.py — Expr base class, AST nodes, statement definitions, Placeholder, and _wrap.

This module MUST NOT import DataTree. Only lower.py touches DataTree.
"""
from __future__ import annotations

# ═══════════════════════════════════════════════════════════════════════════
# _wrap: coerce any build-time value into an Expr node
# ═══════════════════════════════════════════════════════════════════════════

def _wrap(x):
    """Return x unchanged if it's already an Expr, otherwise wrap in Lit."""
    if isinstance(x, Expr):
        return x
    return Lit(x)


# ═══════════════════════════════════════════════════════════════════════════
# Expr base class — operator overloading composes BinOp/UnOp uniformly
# ═══════════════════════════════════════════════════════════════════════════

class Expr:
    """
    Base class for all expression nodes.

    Operator overloading composes BinOp / UnOp nodes uniformly.
    __hash__ = None because __eq__ returns a BinOp, not a bool.
    """

    __hash__ = None

    # -- arithmetic --------------------------------------------------------
    def __add__(self, other): return BinOp("+", self, _wrap(other))
    def __radd__(self, other): return BinOp("+", _wrap(other), self)
    def __sub__(self, other): return BinOp("-", self, _wrap(other))
    def __rsub__(self, other): return BinOp("-", _wrap(other), self)
    def __mul__(self, other): return BinOp("*", self, _wrap(other))
    def __rmul__(self, other): return BinOp("*", _wrap(other), self)
    def __truediv__(self, other): return BinOp("/", self, _wrap(other))
    def __rtruediv__(self, other): return BinOp("/", _wrap(other), self)

    # -- comparison --------------------------------------------------------
    def __lt__(self, other): return BinOp("<", self, _wrap(other))
    def __le__(self, other): return BinOp("<=", self, _wrap(other))
    def __gt__(self, other): return BinOp(">", self, _wrap(other))
    def __ge__(self, other): return BinOp(">=", self, _wrap(other))
    def __eq__(self, other): return BinOp("==", self, _wrap(other))
    def __ne__(self, other): return BinOp("!=", self, _wrap(other))

    # -- boolean (use & | ~, NOT and/or/not) -------------------------------
    def __and__(self, other): return BinOp("&", self, _wrap(other))
    def __or__(self, other): return BinOp("|", self, _wrap(other))
    def __invert__(self): return UnOp("~", self)

    # -- callable: ``expr(lambda x: ...)`` => map statement ----------------
    def __call__(self, fn, *args, **kwargs):
        """Make an Expr callable — sugar for "transform this path with fn".

        ``b.createdAt(lambda t: datetime.fromisoformat(t))`` is equivalent
        to ``assign(b.createdAt, sbo.map(b.createdAt, fn))``.

        Can be used directly as a top-level statement in ``dt.expr(...)``,
        or assigned to a new field via the ``target`` kwarg.

        Returns:
            MapAssign statement (lowered as an invertible assign).
        """
        return MapAssign(target=self, source=self, fn=_wrap(fn),
                         extra_args=tuple(_wrap(a) for a in args),
                         extra_kwargs={k: _wrap(v) for k, v in kwargs.items()})


# ═══════════════════════════════════════════════════════════════════════════
# Value-tier nodes
# ═══════════════════════════════════════════════════════════════════════════

class Lit(Expr):
    """A literal value (numbers, numpy scalars, lambdas, level= ints).

    At evaluation time the value is passed through unchanged.
    Lambdas stored here will be called by the FUNCS runtime (sbo ops).
    """

    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __repr__(self):
        return f"Lit({self.value!r})"


class Col(Expr):
    """Leaf reference to a record path.

    Created explicitly via ``Sym("record.age")``.
    Evaluates to ``record.get_leaves(indexer)``.
    """

    __slots__ = ("indexer",)

    def __init__(self, indexer: str):
        self.indexer = indexer

    def __repr__(self):
        return f"Col({self.indexer!r})"


class BinOp(Expr):
    """Binary operation: ``op(left, right)``."""

    __slots__ = ("op", "left", "right")

    def __init__(self, op: str, left: Expr, right: Expr):
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self):
        return f"BinOp({self.op!r}, {self.left!r}, {self.right!r})"


class UnOp(Expr):
    """Unary operation: ``op(operand)``."""

    __slots__ = ("op", "operand")

    def __init__(self, op: str, operand: Expr):
        self.op = op
        self.operand = operand

    def __repr__(self):
        return f"UnOp({self.op!r}, {self.operand!r})"


class Call(Expr):
    """Value-tier operation: ``FUNCS[name](*eval(args), **eval(kwargs))``.

    Built by sbo helpers (flatten, filter, map, reduce) in ops.py.
    """

    __slots__ = ("name", "args", "kwargs")

    def __init__(self, name: str, args=(), kwargs=None):
        self.name = name
        self.args = tuple(args)
        self.kwargs = dict(kwargs) if kwargs else {}

    def __repr__(self):
        return f"Call({self.name!r}, args={self.args!r}, kwargs={self.kwargs!r})"


class Placeholder(Expr):
    """The ``_`` token used inside ``chain()``.

    Must be substituted away by chain at build time.
    Raising at eval time is a safety net.
    """

    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __repr__(self):
        return "_"


# Singleton — exported as `_`
_ = Placeholder()


# ═══════════════════════════════════════════════════════════════════════════
# Statement nodes (data holders — lowering is in lower.py)
# ═══════════════════════════════════════════════════════════════════════════

class Statement:
    """Base class for statement nodes. Lowering logic lives in lower.py."""
    pass


class Assign(Statement):
    """Set a field on every row: ``assign(target, value)``.

    target: Col or PathBuilder (single settable leaf path).
    value:  any Expr (computed per row).
    """

    __slots__ = ("target", "value")

    def __init__(self, target: Expr, value: Expr):
        self.target = target
        self.value = value

    def __repr__(self):
        return f"Assign({self.target!r}, {self.value!r})"


class Keep(Statement):
    """Row-level filter: ``keep(pred)``."""

    __slots__ = ("pred",)

    def __init__(self, pred: Expr):
        self.pred = pred

    def __repr__(self):
        return f"Keep({self.pred!r})"


class Fork(Statement):
    """Conditional branch: ``fork(cond, then_block, else_block)``."""

    __slots__ = ("cond", "then_block", "else_block")

    def __init__(self, cond: Expr, then_block=(), else_block=()):
        self.cond = cond
        self.then_block = tuple(then_block)
        self.else_block = tuple(else_block)

    def __repr__(self):
        return f"Fork({self.cond!r}, then={self.then_block!r}, else={self.else_block!r})"


class Case(Statement):
    """Multi-way branch: ``case((cond1, block1), ..., default=())``."""

    __slots__ = ("clauses", "default")

    def __init__(self, clauses=(), default=()):
        self.clauses = tuple((cond, tuple(block)) for cond, block in clauses)
        self.default = tuple(default)

    def __repr__(self):
        return f"Case(clauses={self.clauses!r}, default={self.default!r})"


class MapAssign(Statement):
    """Apply ``fn(source_value)`` per row and write to ``target``.

    Sugar for ``assign(target, sbo.map(source, fn))`` — produced by
    ``Expr.__call__``. The default target equals the source, so
    ``b.createdAt(lambda t: ...)`` overwrites the field in place
    (invertible). To write to a different field, use the
    ``map_assign(target, source, fn)`` constructor.
    """

    __slots__ = ("target", "source", "fn", "extra_args", "extra_kwargs")

    def __init__(self, target: Expr, source: Expr, fn: Expr,
                 extra_args=(), extra_kwargs=None):
        self.target = target
        self.source = source
        self.fn = fn
        self.extra_args = tuple(extra_args)
        self.extra_kwargs = dict(extra_kwargs) if extra_kwargs else {}

    def __repr__(self):
        return (
            f"MapAssign(target={self.target!r}, source={self.source!r}, "
            f"fn={self.fn!r})"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Statement constructors (free functions)
# ═══════════════════════════════════════════════════════════════════════════

def assign(target, value):
    """Return [Assign(...)] as a list so ``expr`` can flatten."""
    return [Assign(_wrap(target), _wrap(value))]


def map_assign(target, source, fn, *args, **kwargs):
    """Map a function over a per-row source value and write to ``target``.

    Equivalent to ``assign(target, sbo.map(source, fn, *args, **kwargs))``,
    but expressed at statement tier.
    """
    return MapAssign(
        target=_wrap(target),
        source=_wrap(source),
        fn=_wrap(fn),
        extra_args=tuple(_wrap(a) for a in args),
        extra_kwargs={k: _wrap(v) for k, v in kwargs.items()},
    )


def keep(pred):
    """Return a Keep statement."""
    return Keep(_wrap(pred))


def fork(cond, then_block=(), else_block=()):
    """Return a Fork statement."""
    return Fork(_wrap(cond), then_block, else_block)


def case(*clauses, default=()):
    """Return a Case statement.

    ``case((cond1, block1), (cond2, block2), default=default_block)``
    """
    return Case(clauses, default)


# ═══════════════════════════════════════════════════════════════════════════
# AST walking helpers
# ═══════════════════════════════════════════════════════════════════════════

def _children(node):
    """Return a list of (field_name, child_node) for AST walking."""
    if isinstance(node, Lit):
        return []
    if isinstance(node, (Col,)):  # PathBuilder handled by namespace.py
        return []
    if isinstance(node, Placeholder):
        return []
    if isinstance(node, BinOp):
        return [("left", node.left), ("right", node.right)]
    if isinstance(node, UnOp):
        return [("operand", node.operand)]
    if isinstance(node, Call):
        result = [(f"_arg{i}", a) for i, a in enumerate(node.args)]
        result.extend((f"_kw_{k}", v) for k, v in node.kwargs.items())
        return result
    # Statement nodes — not typically walked by substitute but included for completeness
    if isinstance(node, Assign):
        return [("target", node.target), ("value", node.value)]
    if isinstance(node, Keep):
        return [("pred", node.pred)]
    if isinstance(node, Fork):
        result = [("cond", node.cond)]
        result.extend((f"_then{i}", s) for i, s in enumerate(node.then_block))
        result.extend((f"_else{i}", s) for i, s in enumerate(node.else_block))
        return result
    if isinstance(node, Case):
        result = []
        for i, (cond, block) in enumerate(node.clauses):
            result.append((f"_clause{i}_cond", cond))
            result.extend((f"_clause{i}_{j}", s) for j, s in enumerate(block))
        result.extend((f"_default{i}", s) for i, s in enumerate(node.default))
        return result
    return []


def substitute(node, token, replacement):
    """Deep AST walk: replace every occurrence of ``token`` with ``replacement``.

    Used by ``chain()`` at build time — no runtime register needed.
    """
    if node is token:
        return replacement
    if isinstance(node, (Lit, Col, Placeholder)):
        return node
    # Handle PathBuilder from namespace.py (lazy import to avoid circular)
    if type(node).__name__ == "PathBuilder":
        return node
    if isinstance(node, BinOp):
        return BinOp(
            node.op,
            substitute(node.left, token, replacement),
            substitute(node.right, token, replacement),
        )
    if isinstance(node, UnOp):
        return UnOp(node.op, substitute(node.operand, token, replacement))
    if isinstance(node, Call):
        new_args = [substitute(a, token, replacement) for a in node.args]
        new_kwargs = {k: substitute(v, token, replacement) for k, v in node.kwargs.items()}
        return Call(node.name, new_args, new_kwargs)
    return node
