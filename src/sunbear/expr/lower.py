"""lower.py — lower expr statements (tuples) to DataTree operations.

Statements are tuples:
  ("assign", path, expr)         → dt.assign_at(path, compile(expr))
  ("keep", pred)                 → dt.filter(lambda r, m: bool(compile(pred)(r)))
  ("filter", path, pred_expr)    → intra-record lazy filter via sbo.filter
  ("map", path, fn_expr)         → intra-record sbo.map
  ("flatten", path, level)       → intra-record sbo.flatten
  ("fork", cond, then_stmts, else_stmts) → dt.apply(branch_fn)
  ("case", clauses, default)     → dt.apply(case_fn)
  ("project", (key, ...))        → dt.apply(project_fn) — drop unselected fields
  ("rename", src, dst)           → dt.rename(src.indexer=dst.indexer)
  ("drop", (path, ...))          → dt.drop(*paths)
  ("copy", src, dst)             → dt.copy(src, dst)
  ("default", target, value)     → dt.apply(default_fn) — set if None
  ("nest", (paths...,), into)    → dt.apply(nest_fn) — group fields
  ("unnest", path)               → dt.apply(unnest_fn) — flatten nested dict
  ("assert", pred, message)      → dt.filter(check_fn) — raise on failure
  ("mask", target, pred, value)  → dt.apply(mask_fn) — conditional set
  ("coalesce", (paths...,), target) → dt.apply(coalesce_fn) — first non-None

Statement builders:
  assign(target, value)          — single assign (positional)
  assign(key=value, ...)         — keyword sugar (multiple assigns)
  keep(pred)
  filter_field(target, pred)
  map_field(target, fn)
  flatten(target, level=-1)
  fork(cond, then_block, else_block)
  case(*clauses, default=())
  select(*args, **kwargs)        — project/rename, returns list of stmts
  rename(**mapping)               — move fields, returns list of stmts
  drop(*paths)                   — remove fields
  copy_field(src, dst)           — duplicate field
  default(target, value)         — set if None
  nest(*paths, into=)            — group fields into nested dict
  unnest(path)                   — flatten nested dict
  assert_(pred, message=None)    — raise on bad rows
  mask(target, pred, value)      — conditional set
  cast(target, type_)            — type coercion
  upper(target)                  — uppercase string
  lower_str(target)              — lowercase string
  trim(target)                   — strip whitespace
  round_field(target, ndigits)   — round numeric field
  coalesce(*paths, target=)      — first non-None value
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from .ast import Expr, _wrap, Call, Lit, Path
from .eval import compile


# ═══════════════════════════════════════════════════════════════════════════
# Statement constructors (return tuples)
# ═══════════════════════════════════════════════════════════════════════════

def assign(target=None, value=None, **kwargs):
    """Create assign statement(s).

    Positional: ``assign(b.target, value)`` → single statement tuple.
    Keyword:    ``assign(tags=b.source, x=42)`` → list of statement tuples,
                one per kwarg.  ``_flatten_stmts`` handles both transparently.
    """
    stmts = []
    if target is not None:
        stmts.append(("assign", _wrap(target), _wrap(value)))
    for key, val in kwargs.items():
        stmts.append(("assign", _wrap(Path(key)), _wrap(val)))
    if not stmts:
        raise TypeError("assign() requires positional (target, value) or keyword arguments")
    return stmts if len(stmts) > 1 else stmts[0]


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


def select(*args, **kwargs):
    """Project / rename fields, then discard everything else.

    kwargs: ``select(tags=b.commit.record.facets.features.tag)``
        assigns the RHS to the kwarg key (rename / move).
    args: ``select(b.createdAt)``
        keeps the field at its current path (top-level key extracted).

    Returns a **list** of statement tuples (assigns + project).
    """
    keep_keys: list[str] = []
    stmts: list = []

    for key, value in kwargs.items():
        stmts.append(("assign", _wrap(Path(key)), _wrap(value)))
        keep_keys.append(key)

    for path_expr in args:
        p = _wrap(path_expr)
        # Extract the top-level key from the path.
        if isinstance(p, Path):
            top = p.indexer.split(".")[0]
        else:
            raise TypeError(f"select: positional args must be paths, got {p!r}")
        keep_keys.append(top)

    if not keep_keys:
        raise ValueError("select() requires at least one positional or keyword argument")

    stmts.append(("project", tuple(keep_keys)))
    return stmts


# ═══════════════════════════════════════════════════════════════════════════
# Structural row-wise ops (1→1 shape)
# ═══════════════════════════════════════════════════════════════════════════

def rename(**mapping):
    """Move fields: ``rename(old_name="new_name")``.

    Returns a list of statement tuples.
    """
    stmts = []
    for old, new in mapping.items():
        stmts.append(("rename", _wrap(Path(old)), _wrap(Path(new))))
    if not stmts:
        raise TypeError("rename() requires at least one keyword argument")
    return stmts


def drop(*paths):
    """Remove fields by path. ``drop(b.temp, b.internal_id)``."""
    return ("drop", tuple(_wrap(p) for p in paths))


def copy_field(src, dst):
    """Copy a field value to a new path (keeps source).

    ``copy_field(b.name, b.backup)``
    """
    return ("copy", _wrap(src), _wrap(dst))


def default(target, value):
    """Set a field only if it is currently ``None`` (missing).

    ``default(b.tier, "standard")``
    """
    return ("default", _wrap(target), _wrap(value))


def nest(*paths, into):
    """Group fields into a nested dict under ``into``.

    ``nest(b.first, b.last, into="name")``
    → each row gets ``{name: {first: ..., last: ...}}`` and top-level
    ``first``, ``last`` are removed.
    """
    return ("nest", tuple(_wrap(p) for p in paths), str(into))


def unnest(path):
    """Flatten a nested dict into top-level fields.

    ``unnest(b.address)``
    → ``address.street``, ``address.city`` become top-level ``street``, ``city``.
    The original nested field is removed.
    """
    return ("unnest", _wrap(path))


# ═══════════════════════════════════════════════════════════════════════════
# Conditional row-wise ops (1→{0,1} via skip metadata)
# ═══════════════════════════════════════════════════════════════════════════

def assert_(pred, message=None):
    """Raise ``ValueError`` when *pred* is falsy.

    Use :func:`keep` when failing rows should be filtered instead.
    """
    return ("assert", _wrap(pred), message)


def mask(target, pred, value):
    """Set *target* to *value* only where *pred* is true; otherwise leave
    *target* unchanged (or ``None`` if absent).

    ``mask(b.flag, b.age < 18, "minor")``
    """
    return ("mask", _wrap(target), _wrap(pred), _wrap(value))


# ═══════════════════════════════════════════════════════════════════════════
# Sugar (common assign shortcuts)
# ═══════════════════════════════════════════════════════════════════════════

def cast(target, type_):
    """Type coercion: ``cast(b.age, int)`` → ``assign(b.age, int(b.age))``."""
    return ("assign", _wrap(target), Call("__cast", [_wrap(target)], {"type": Lit(type_)}))


def upper(target):
    """Uppercase a string field: ``upper(b.name)``."""
    return ("assign", _wrap(target), Call("__upper", [_wrap(target)]))


def lower_str(target):
    """Lowercase a string field: ``lower_str(b.name)``."""
    return ("assign", _wrap(target), Call("__lower", [_wrap(target)]))


def trim(target):
    """Strip whitespace from a string field: ``trim(b.name)``."""
    return ("assign", _wrap(target), Call("__trim", [_wrap(target)]))


def round_field(target, ndigits=0):
    """Round a numeric field: ``round_field(b.score, 2)``."""
    return ("assign", _wrap(target), Call("__round", [_wrap(target)], {"ndigits": _wrap(ndigits)}))


def coalesce(*paths, target):
    """Assign the first non-``None`` value among *paths* to *target*.

    ``coalesce(b.nickname, b.name, target=b.display)``
    """
    t = target
    if isinstance(t, Path):
        t = t.indexer
    elif hasattr(t, "indexer"):
        t = t.indexer
    return ("coalesce", tuple(_wrap(p) for p in paths), str(t))


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

    if kind == "project":
        _, keep_keys = stmt
        keep_set = set(keep_keys)
        def _project_row(r):
            to_drop = [k for k in list(r.data.keys()) if k not in keep_set]
            for k in to_drop:
                del r.data[k]
        from ..Record import Record
        def _row_fn(r):
            nr = Record(dict(r.data), dict(r.meta))
            _project_row(nr)
            return nr
        return dt.apply(_row_fn)

    # ---- Structural ops ----

    if kind == "rename":
        _, src, dst = stmt
        return dt.rename(**{src.indexer: dst.indexer})

    if kind == "drop":
        _, paths = stmt
        return dt.drop(*paths)

    if kind == "copy":
        _, src, dst = stmt
        return dt.copy(src, dst)

    if kind == "default":
        _, target, value = stmt
        f_val = compile(value)
        from ..Record import Record
        def _default_row(r):
            nr = Record(dict(r.data), dict(r.meta))
            if nr.get(target) is None:
                nr.set(target, f_val(r))
            return nr
        return dt.apply(_default_row)

    if kind == "nest":
        _, paths, into = stmt
        from ..Record import Record
        def _nest_row(r):
            nr = Record(dict(r.data), dict(r.meta))
            nested = {}
            for p in paths:
                key = p.indexer.split(".")[-1]
                nested[key] = nr.get(p)
                nr.delete(p)
            nr.set(into, nested)
            return nr
        return dt.apply(_nest_row)

    if kind == "unnest":
        _, path = stmt
        from ..Record import Record
        def _unnest_row(r):
            nr = Record(dict(r.data), dict(r.meta))
            val = nr.get(path)
            if isinstance(val, dict):
                for k, v in val.items():
                    nr.set(k, v)
                nr.delete(path)
            return nr
        return dt.apply(_unnest_row)

    # ---- Conditional ops (1→{0,1}) ----

    if kind == "assert":
        _, pred, message = stmt
        f = compile(pred)
        error_message = message or "SunBear assertion failed"
        def _check(r, m, _f=f, _msg=error_message):
            if not bool(_f(r)):
                raise ValueError(_msg)
            return True
        return dt.filter(_check)

    if kind == "mask":
        _, target, pred, value = stmt
        f_pred = compile(pred)
        f_val = compile(value)
        from ..Record import Record
        def _mask_row(r):
            nr = Record(dict(r.data), dict(r.meta))
            if bool(f_pred(r)):
                nr.set(target, f_val(r))
            return nr
        return dt.apply(_mask_row)

    # ---- Sugar ops ----

    if kind == "coalesce":
        _, paths, target = stmt
        from ..Record import Record
        def _coalesce_row(r):
            nr = Record(dict(r.data), dict(r.meta))
            for p in paths:
                v = nr.get(p)
                if v is not None:
                    nr.set(target, v)
                    return nr
            return nr
        return dt.apply(_coalesce_row)

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
    if kind == "rename":
        _, src, dst = stmt
        v = r.get(src)
        r.delete(src)
        if v is not None:
            r.set(dst, v)
        return
    if kind == "drop":
        _, paths = stmt
        for p in paths:
            r.delete(p)
        return
    if kind == "copy":
        _, src, dst = stmt
        v = r.get(src)
        if v is not None:
            r.set(dst, v)
        return
    if kind == "default":
        _, target, value = stmt
        if r.get(target) is None:
            r.set(target, compile(value)(r))
        return
    if kind == "mask":
        _, target, pred, value = stmt
        if bool(compile(pred)(r)):
            r.set(target, compile(value)(r))
        return
    if kind == "coalesce":
        _, paths, target = stmt
        for p in paths:
            v = r.get(p)
            if v is not None:
                r.set(target, v)
                return
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
                                "fork", "case", "project",
                                "rename", "drop", "copy", "default",
                                "nest", "unnest",
                                "assert", "mask", "coalesce"}:
            out.append(item)
        elif isinstance(item, (list, tuple)):
            out.extend(_flatten_stmts(item))
        else:
            out.append(item)
    return out
