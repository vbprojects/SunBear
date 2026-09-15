"""Statement builders and a shared compiled row-local executor."""

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
        raise TypeError(
            "assign() requires positional (target, value) or keyword arguments"
        )
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
    """Atomic projection. Positional nested paths retain their top-level object.

    Keyword names and aliases are literal output keys; RHSs see the input row.
    """
    from ._sugar import Alias
    from ..selectors import Selector

    fields = []
    for arg in args:
        if isinstance(arg, Alias):
            fields.append((arg.name, _wrap(arg.value)))
        elif isinstance(arg, Selector):
            fields.append((arg, None))
        else:
            path = Path(arg) if isinstance(arg, str) else arg
            if not isinstance(path, Path):
                raise TypeError(
                    "select positional fields must be paths, aliases, or selectors"
                )
            top = path.indexer.segments[0].value
            fields.append((top, Path(PathSpec((Key(top),)))))
    fields.extend((k, _wrap(v)) for k, v in kwargs.items())
    if not fields:
        raise ValueError("select requires fields")
    return [("select", tuple(fields))]


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
    return (
        "assign",
        _wrap(target),
        Call("__cast", [_wrap(target)], {"type": Lit(type_)}),
    )


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
    return (
        "assign",
        _wrap(target),
        Call("__round", [_wrap(target)], {"ndigits": _wrap(ndigits)}),
    )


def coalesce(*paths, target):
    """Assign the first non-``None`` value among *paths* to *target*.

    ``coalesce(b.nickname, b.name, target=b.display)``
    """
    t = target
    if isinstance(t, Path):
        t = t.indexer
    elif hasattr(t, "indexer"):
        t = t.indexer
    return ("coalesce", tuple(_wrap(p) for p in paths), t)


from ..record import Record
from ..paths import MISSING, PathSpec, Key
import copy


class TransformationError(ValueError):
    """Pipeline failure with step/row context and the original exception cause."""

    def __init__(self, step, row, kind, path=None):
        self.step, self.row, self.kind, self.path = step, row, kind, path
        super().__init__(
            f"Step {step} ({kind}), row {row}"
            + (f", path {path}" if path is not None else "")
        )


def _flatten_stmts(items):
    out = []
    for item in items:
        if isinstance(item, (tuple, list)) and item and isinstance(item[0], str):
            out.append(tuple(item))
        elif isinstance(item, (tuple, list)):
            out.extend(_flatten_stmts(item))
        else:
            raise TypeError(f"Expected a statement, got {type(item).__name__}")
    return out


def _path(value):
    if isinstance(value, Lit):
        value = value.value
    Record.resolve(value)  # validate before consuming a row
    return value


def _compile_statement(stmt):
    kind, *args = stmt
    if kind == "select":
        from ..selectors import Selector

        fields = [
            (key, None if isinstance(key, Selector) else compile(value))
            for key, value in args[0]
        ]

        def apply(r):
            from ..paths import output_value

            result = {}
            for key, fn in fields:
                if isinstance(key, Selector):
                    for name in key.resolve(r.data):
                        if name in result:
                            raise ValueError(f"Duplicate projection key: {name}")
                        result[name] = r.data[name]
                else:
                    if key in result:
                        raise ValueError(f"Duplicate projection key: {key}")
                    result[key] = fn(r)
            r.data = copy.deepcopy(output_value(result))
            return r

        return apply
    if kind in {"transform_fields", "rename_fields"}:
        from ..selectors import _check

        selector = _check(args[0])
        if kind == "transform_fields":
            from .eval import _compile

            fn = _compile(args[1], frozenset({"field_value"}))
        else:
            fn = args[1]
            if not callable(fn):
                raise TypeError("rename_fields requires a callable")

        def apply(r):
            original = r.data
            result = dict(original)
            selected = selector.resolve(original)
            if kind == "transform_fields":
                for key in selected:
                    result[key] = fn(r, {"field_value": original[key]})
            else:
                result = {k: v for k, v in original.items() if k not in selected}
                for key in selected:
                    name = fn(key)
                    if not isinstance(name, str) or name in result:
                        raise ValueError("Invalid or duplicate renamed field")
                    result[name] = original[key]
            from ..paths import output_value

            r.data = copy.deepcopy(output_value(result))
            return r

        return apply
    if kind in {"require_fields", "drop_nulls"}:
        from ..selectors import Selector

        fields = args[0]
        for field in fields:
            if not isinstance(field, Selector):
                _path(field)

        def apply(r):
            paths = []
            for field in fields:
                paths.extend(
                    Path(PathSpec((Key(k),))) for k in field.resolve(r.data)
                ) if isinstance(field, Selector) else paths.append(field)
            if not fields:
                paths = [Path(PathSpec((Key(k),))) for k in r.data]
            for path in paths:
                value = r.get(path, MISSING)
                if kind == "require_fields" and value is MISSING:
                    raise ValueError(f"Missing required field: {path}")
                if kind == "drop_nulls" and (value is MISSING or value is None):
                    return None
            return r

        return apply
    if kind == "unnest_prefix":
        path, prefix = _path(args[0]), args[1]
        if not isinstance(prefix, str):
            raise TypeError("prefix must be string")

        def apply(r):
            value = r.get(path, MISSING)
            if value is None or value is MISSING:
                return r
            if not isinstance(value, dict):
                raise TypeError("unnest expects object")
            r.delete(path)
            for key, v in value.items():
                dest = PathSpec((Key(prefix + key),))
                if r.get(dest, MISSING) is not MISSING:
                    raise ValueError(f"unnest collision: {prefix + key}")
                r.set(dest, v)
            return r

        return apply
    if kind in {"assign", "default", "mask"}:
        path = _path(args[0])
        val = compile(args[-1])
        pred = compile(args[1]) if kind == "mask" else None

        def apply(r):
            if (
                kind == "default"
                and r.get(path, MISSING) is not MISSING
                and r.get(path) is not None
            ):
                return r
            if pred is None or bool(pred(r)):
                r.set(path, val(r))
            return r

        return apply
    if kind in {"keep", "assert"}:
        pred = compile(args[0])

        def apply(r):
            if bool(pred(r)):
                return r
            if kind == "keep":
                return None
            raise ValueError(
                args[1] if args[1] is not None else "SunBear assertion failed"
            )

        return apply
    if kind in {"filter", "map", "flatten"}:
        path, value = _path(args[0]), compile(args[1])
        from .eval import FUNCS

        fn = FUNCS[kind]

        def apply(r):
            current = r.get(path, MISSING)
            # Expression predicates evaluate against each list item; literal
            # callbacks are called directly on the item.
            if kind == "flatten":
                result = fn(current, value(r))
            else:
                callback = (
                    value(r)
                    if isinstance(args[1], Lit)
                    else (
                        lambda item: value(
                            Record(item) if isinstance(item, dict) else item
                        )
                    )
                )
                result = (
                    fn(current, callback, r)
                    if kind == "filter"
                    else fn(current, callback)
                )
            r.set(path, result)
            return r

        return apply
    if kind == "fork":
        cond = compile(args[0])
        yes, no = compile_plan(args[1]), compile_plan(args[2])
        return lambda r: (yes if bool(cond(r)) else no).execute(r, clone=False)
    if kind == "case":
        clauses = [(compile(c), compile_plan(block)) for c, block in args[0]]
        default = compile_plan(args[1])

        def apply(r):
            for pred, block in clauses:
                if bool(pred(r)):
                    return block.execute(r, clone=False)
            return default.execute(r, clone=False)

        return apply
    if kind == "project":
        keys = frozenset(args[0])

        def apply(r):
            r.data = {k: v for k, v in r.data.items() if k in keys}
            return r

        return apply
    if kind in {"rename", "copy"}:
        src, dst = map(_path, args)

        def apply(r):
            return r.mv(src, dst) if kind == "rename" else r.cpy(src, dst)

        return apply
    if kind == "drop":
        paths = tuple(map(_path, args[0]))

        def apply(r):
            for path in paths:
                r.delete(path)
            return r

        return apply
    if kind == "nest":
        paths, into = tuple(map(_path, args[0])), _path(args[1])

        def apply(r):
            values = {}
            for path in paths:
                spec = path.indexer if isinstance(path, Path) else PathSpec.dotted(path)
                key = spec.segments[-1].value
                value = r.get(path, MISSING)
                if value is not MISSING:
                    values[key] = value
                r.delete(path)
            r.set(into, values)
            return r

        return apply
    if kind == "unnest":
        path = _path(args[0])

        def apply(r):
            value = r.get(path, MISSING)
            if isinstance(value, dict):
                r.delete(path)
                for key, v in value.items():
                    r.set(PathSpec((Key(key),)), v)
            return r

        return apply
    if kind == "coalesce":
        paths, target = tuple(map(_path, args[0])), _path(args[1])

        def apply(r):
            for path in paths:
                value = r.get(path, MISSING)
                if value is not MISSING and value is not None:
                    r.set(target, value)
                    break
            return r

        return apply
    raise TypeError(f"Unsupported statement kind: {kind!r}")


_ARITY = {
    "select": 1,
    "transform_fields": 2,
    "rename_fields": 2,
    "require_fields": 1,
    "drop_nulls": 1,
    "unnest_prefix": 2,
    "assign": 2,
    "default": 2,
    "mask": 3,
    "keep": 1,
    "assert": 2,
    "filter": 2,
    "map": 2,
    "flatten": 2,
    "fork": 3,
    "case": 2,
    "project": 1,
    "rename": 2,
    "copy": 2,
    "drop": 1,
    "nest": 2,
    "unnest": 1,
    "coalesce": 2,
}


class CompiledPlan:
    """Compiled row-local stages. Global/expanding stages are rejected."""

    def __init__(self, statements):
        self.steps = []
        self.stage_kind = "row-local"
        for i, stmt in enumerate(_flatten_stmts(statements), 1):
            if stmt[0] not in _ARITY or len(stmt) - 1 != _ARITY[stmt[0]]:
                raise TypeError(f"Unsupported or malformed statement: {stmt[0]!r}")
            self.steps.append(
                (
                    i,
                    stmt[0],
                    _compile_statement(stmt),
                    getattr(stmt[1], "indexer", None),
                )
            )

    def execute(self, record, row=None, clone=True):
        if clone:
            record = Record(dict(record.data), copy.deepcopy(record.meta))
        for step, kind, fn, path in self.steps:
            try:
                record = fn(record)
            except TransformationError:
                raise
            except Exception as exc:
                error = TransformationError(
                    step, row if row is not None else record.meta.get("i"), kind, path
                )
                # Preserve custom assertion text while retaining contextual diagnostics.
                if kind == "assert":
                    error.args = (f"{error}: {exc}",)
                raise error from exc
            if record is None:
                break
        return record

    def apply(self, dt):
        def rows():
            for i, (record, meta) in enumerate(dt.scan()):
                result = self.execute(record, row=i)
                if result is not None:
                    yield result, result.meta

        return dt._derive(rows)


def compile_plan(statements):
    return CompiledPlan(statements)


def run_expr(dt, *statements):
    return compile_plan(statements).apply(dt)
