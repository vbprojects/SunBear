"""Value conveniences. All builders produce serializable expression nodes."""

from __future__ import annotations
import builtins
import math
import re
from dataclasses import dataclass
from functools import reduce
from ..paths import MISSING, PathSpec, output_value


def node(kind, *args, **options):
    from .ast import Sugar, _wrap

    return Sugar(kind, tuple(_wrap(a) for a in args), options)


class ValueMethods:
    @property
    def str(self):
        return StringAccessor(self)

    @property
    def list(self):
        return ListAccessor(self)

    @property
    def obj(self):
        return ObjectAccessor(self)

    def is_missing(self):
        return node("is_missing", self)

    def fill_null(self, value):
        return node("fill_null", self, value)

    def fill_missing(self, value):
        return node("fill_missing", self, value)

    def coalesce(self, *values):
        return node("coalesce", self, *values)

    def is_in(self, values):
        return node("is_in", self, values)

    def not_in(self, values):
        return ~self.is_in(values)

    def between(self, low, high, *, closed="both"):
        if closed not in ("both", "left", "right", "none"):
            raise ValueError("Invalid closed policy")
        return (self >= low if closed in ("both", "left") else self > low) & (
            self <= high if closed in ("both", "right") else self < high
        )

    def cast(self, type_, *, errors="raise"):
        if type_ not in (str, int, float, bool):
            raise TypeError("cast supports str, int, float, bool")
        if errors not in ("raise", "null"):
            raise ValueError("errors must be raise or null")
        return node("cast", self, type=type_.__name__, errors=errors)

    def replace(self, mapping, *, default=MISSING):
        return node("replace", self, mapping, default)

    def apply(self, fn):
        if not callable(fn):
            raise TypeError("apply requires a callable")
        return node("apply", self, fn)

    def as_(self, name):
        return Alias(name, self)

    def asc(self):
        return SortKey(self, False)

    def desc(self):
        return SortKey(self, True)

    def abs(self):
        return node("num.abs", self)

    def round(self, ndigits=0):
        return node("num.round", self, ndigits)

    def floor(self):
        return node("num.floor", self)

    def ceil(self):
        return node("num.ceil", self)

    def clip(self, low, high):
        return node("num.clip", self, low, high)

    def sign(self):
        return node("num.sign", self)

    def sqrt(self):
        return node("num.sqrt", self)

    def log(self, base=math.e):
        return node("num.log", self, base)

    def exp(self):
        return node("num.exp", self)

    def is_finite(self):
        return node("num.is_finite", self)

    def is_nan(self):
        return node("num.is_nan", self)

    def __abs__(self):
        return self.abs()

    def __round__(self, ndigits=0):
        return self.round(ndigits)

    def __neg__(self):
        return node("num.neg", self)

    def __pos__(self):
        return node("num.pos", self)

    def __floordiv__(self, other):
        return node("num.floordiv", self, other)

    def __rfloordiv__(self, other):
        return node("num.floordiv", other, self)

    def __mod__(self, other):
        return node("num.mod", self, other)

    def __rmod__(self, other):
        return node("num.mod", other, self)

    def __pow__(self, other):
        return node("num.pow", self, other)

    def __rpow__(self, other):
        return node("num.pow", other, self)


@dataclass(frozen=True)
class Alias:
    name: str
    value: object

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("Alias must be a nonempty string")


@dataclass(frozen=True)
class SortKey:
    value: object
    descending: bool = False


class StringAccessor:
    def __init__(self, value):
        self._value = value

    def _call(self, name, *args, **options):
        return node("str." + name, self._value, *args, **options)

    def lower(self):
        return self._call("lower")

    def upper(self):
        return self._call("upper")

    def title(self):
        return self._call("title")

    def capitalize(self):
        return self._call("capitalize")

    def casefold(self):
        return self._call("casefold")

    def strip(self, chars=None):
        return self._call("strip", chars)

    def lstrip(self, chars=None):
        return self._call("lstrip", chars)

    def rstrip(self, chars=None):
        return self._call("rstrip", chars)

    def normalize_whitespace(self):
        return self._call("normalize_whitespace")

    def contains(self, pattern, *, regex=False):
        return self._call("contains", pattern, regex=regex)

    def starts_with(self, prefix):
        return self._call("startswith", prefix)

    def ends_with(self, suffix):
        return self._call("endswith", suffix)

    def matches(self, pattern):
        return self._call("matches", pattern, regex=True)

    def replace(self, old, new, *, count=1, regex=False):
        return self._call("replace", old, new, count, regex=regex)

    def replace_all(self, old, new, *, regex=False):
        return self.replace(old, new, count=-1, regex=regex)

    def remove_prefix(self, prefix):
        return self._call("removeprefix", prefix)

    def remove_suffix(self, suffix):
        return self._call("removesuffix", suffix)

    def split(self, sep=None, maxsplit=-1):
        return self._call("split", sep, maxsplit)

    def split_lines(self):
        return self._call("splitlines")

    def partition(self, sep):
        return self._call("partition", sep)

    def extract(self, pattern, group=0):
        return self._call("extract", pattern, group, regex=True)

    def extract_all(self, pattern):
        return self._call("extract_all", pattern, regex=True)

    def slice(self, start=None, stop=None, step=None):
        return self._call("slice", start, stop, step)

    def head(self, n=5):
        return self.slice(0, n)

    def tail(self, n=5):
        return self._call("tail", n)

    def len(self):
        return self._call("len")

    def pad_left(self, width, fill=" "):
        return self._call("rjust", width, fill)

    def pad_right(self, width, fill=" "):
        return self._call("ljust", width, fill)

    def zfill(self, width):
        return self._call("zfill", width)


class ListAccessor:
    def __init__(self, value):
        self._value = value

    def _call(self, name, *args, **options):
        return node("list." + name, self._value, *args, **options)

    def len(self):
        return self._call("len")

    def count(self):
        return self.len()

    def get(self, index, default=None):
        return self._call("get", index, default)

    def first(self, default=None):
        return self.get(0, default)

    def last(self, default=None):
        return self.get(-1, default)

    def slice(self, start=None, stop=None, step=None):
        return self._call("slice", start, stop, step)

    def head(self, n=5):
        return self.slice(0, n)

    def tail(self, n=5):
        return self._call("tail", n)

    def map(self, expression, *, item=None):
        return self._scoped("map", expression, item)

    def filter(self, expression, *, item=None):
        return self._scoped("filter", expression, item)

    def flat_map(self, expression, *, item=None):
        return self._scoped("flat_map", expression, item)

    def sort_by(self, expression, *, item=None, reverse=False):
        return self._scoped("sort_by", expression, item, reverse=reverse)

    def any(self, expression=None, *, item=None):
        return (
            self._call("any")
            if expression is None
            else self._scoped("any", expression, item)
        )

    def all(self, expression=None, *, item=None):
        return (
            self._call("all")
            if expression is None
            else self._scoped("all", expression, item)
        )

    def count_where(self, expression, *, item=None):
        return self._scoped("count_where", expression, item)

    def _scoped(self, name, expression, symbol, **options):
        from .ast import Item, Sugar, _wrap

        if callable(expression):
            return self._call("python_" + name, expression, **options)
        if symbol is None:
            free = free_items(_wrap(expression))
            if len(free) != 1:
                raise ValueError("Specify item= for zero or multiple free item symbols")
            symbol = Item(next(iter(free)))
        if not isinstance(symbol, Item) or symbol.indexer.segments:
            raise TypeError("item= must be an item root")
        return Sugar(
            "list.scoped_" + name,
            (_wrap(self._value), _wrap(expression)),
            dict(options, symbol=symbol.symbol),
        )

    def flatten(self, level=-1):
        return self._call("flatten", level)

    def contains(self, value):
        return self._call("contains", value)

    def is_empty(self):
        return self.len() == 0

    def drop_nulls(self):
        return self._call("drop_nulls")

    def unique(self):
        return self._call("unique")

    def sort(self, *, reverse=False):
        return self._call("sort", reverse=reverse)

    def reverse(self):
        return self._call("reverse")

    def sum(self):
        return self._call("sum")

    def mean(self):
        return self._call("mean")

    def min(self):
        return self._call("min")

    def max(self):
        return self._call("max")

    def reduce(self, fn, initial=MISSING):
        return self._call("reduce", fn, initial)

    def concat(self, *others):
        return self._call("concat", *others)

    def append(self, value):
        return self._call("append", value)

    def prepend(self, value):
        return self._call("prepend", value)

    def zip(self, *others):
        return self._call("zip", *others)

    def enumerate(self, start=0):
        return self._call("enumerate", start)

    def chunk(self, size):
        return self._call("chunk", size)

    def join(self, sep=""):
        return self._call("join", sep)

    def union(self, other):
        return self._call("union", other)

    def intersection(self, other):
        return self._call("intersection", other)

    def difference(self, other):
        return self._call("difference", other)


class ObjectAccessor:
    def __init__(self, value):
        self._value = value

    def _call(self, name, *args, **options):
        return node("obj." + name, self._value, *args, **options)

    def get(self, key, default=None):
        return self._call("get", key, default)

    def keys(self):
        return self._call("keys")

    def values(self):
        return self._call("values")

    def entries(self):
        return self._call("entries")

    def pick(self, *keys):
        return self._call("pick", *keys)

    def omit(self, *keys):
        return self._call("omit", *keys)

    def merge(self, other, *, conflicts="right"):
        if conflicts not in ("right", "left", "raise"):
            raise ValueError("Invalid conflict policy")
        return self._call("merge", other, conflicts=conflicts)

    def rename(self, **mapping):
        return self._call("rename", mapping)


def free_items(expr):
    from .ast import Item, Sugar, BinOp, UnOp, Call

    if isinstance(expr, Item):
        return {expr.symbol}
    if isinstance(expr, BinOp):
        return free_items(expr.left) | free_items(expr.right)
    if isinstance(expr, UnOp):
        return free_items(expr.operand)
    if isinstance(expr, (Sugar, Call)):
        sets = [free_items(a) for a in expr.args]
        if isinstance(expr, Sugar) and expr.kind.startswith("list.scoped_"):
            sets[1].discard(expr.options["symbol"])
        if isinstance(expr, Call):
            sets += [free_items(a) for a in expr.kwargs.values()]
        return set().union(*sets)
    return set()


def _list(v):
    if not isinstance(v, list):
        raise TypeError(f"Expected list; received {type(v).__name__}")
    return v


def _unique(values):
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def compile_sugar(expr, compile_, scope):
    kind, options = expr.kind, expr.options
    if kind.startswith("list.scoped_"):
        symbol = options["symbol"]
        if symbol in scope:
            raise ValueError(
                f"Item symbol {symbol!r} is already bound; use a distinct nested item"
            )
        source = compile_(expr.args[0], scope)
        body = compile_(expr.args[1], scope | {symbol})
        op = kind.removeprefix("list.scoped_")

        def run(r, env):
            values = source(r, env)
            if values is MISSING or values is None:
                return values
            _list(values)

            def evaluate(v):
                return body(r, dict(env, **{symbol: v}))

            return _list_scoped(op, values, evaluate, options)

        return run
    args = [compile_(a, scope) for a in expr.args]
    if kind in ("coalesce", "fill_null", "fill_missing"):

        def fallback(r, env):
            value = args[0](r, env)
            if kind == "fill_null":
                return args[1](r, env) if value is None else value
            if kind == "fill_missing":
                return args[1](r, env) if value is MISSING else value
            for arg in args[1:]:
                if value is not MISSING and value is not None:
                    return value
                value = arg(r, env)
            return value

        return fallback
    if kind == "when":

        def choose(r, env):
            for i in range(0, len(args) - 1, 2):
                if bool(args[i](r, env)):
                    return args[i + 1](r, env)
            return args[-1](r, env)

        return choose
    if kind == "object":
        return lambda r, env: output_value(
            dict(zip(options["keys"], (a(r, env) for a in args)))
        )
    if kind == "array":
        return lambda r, env: output_value([a(r, env) for a in args])
    # Static regular expressions are validated and compiled once per plan.
    regex = None
    if kind.startswith("str.") and options.get("regex"):
        from .ast import Lit

        if not isinstance(expr.args[1], Lit) or not isinstance(expr.args[1].value, str):
            raise TypeError("Regex patterns must be static strings")
        regex = re.compile(expr.args[1].value)

    def run(r, env):
        value = args[0](r, env) if args else None
        if kind == "is_missing":
            return value is MISSING
        if kind == "apply":
            return args[1](r, env)(value)
        if value is MISSING or value is None:
            return value
        # get defaults and replacement fallbacks are lazy too.
        if kind in ("list.get", "obj.get"):
            expected = list if kind == "list.get" else dict
            if not isinstance(value, expected):
                raise TypeError(f"Expected {expected.__name__}")
            key = args[1](r, env)
            if expected is list and type(key) is not int:
                raise TypeError("List index must be int")
            try:
                return value[key]
            except (KeyError, IndexError):
                return args[2](r, env)
        if kind == "replace":
            mapping = args[1](r, env)
            if value in mapping:
                return mapping[value]
            default = args[2](r, env)
            return value if default is MISSING else default
        rest = [a(r, env) for a in args[1:]]
        if kind == "is_in":
            return value in rest[0]
        if kind == "cast":
            try:
                return getattr(builtins, options["type"])(value)
            except (ValueError, TypeError, OverflowError):
                if options["errors"] == "null":
                    return None
                raise
        if kind.startswith("str."):
            return _string(kind[4:], value, rest, regex)
        if kind.startswith("list."):
            return _list_op(kind[5:], _list(value), rest, options)
        if kind.startswith("obj."):
            return _object(kind[4:], value, rest, options)
        if kind.startswith("num."):
            if type(value) not in (int, float):
                raise TypeError("Expected a number")
            return _NUMERIC[kind[4:]](value, *rest)
        if kind == "concat_str":
            if any(v is MISSING for v in rest):
                return MISSING
            if any(v is None for v in rest):
                return None
            return options["sep"].join([value, *rest])
        if kind == "format_str":
            return value.format(*rest, **options)
        raise TypeError(f"Unknown value operation: {kind}")

    return run


def _string(op, value, args, regex):
    if not isinstance(value, str):
        raise TypeError(f"Expected string; received {type(value).__name__}")
    if regex is not None:
        if op == "contains":
            return regex.search(value) is not None
        if op == "matches":
            return regex.fullmatch(value) is not None
        if op == "replace":
            return (
                value
                if args[2] == 0
                else regex.sub(args[1], value, count=0 if args[2] < 0 else args[2])
            )
        if op == "extract":
            match = regex.search(value)
            return match.group(args[1]) if match else None
        if op == "extract_all":
            return output_value(
                [list(v) if isinstance(v, tuple) else v for v in regex.findall(value)]
            )
    if op == "contains":
        return args[0] in value
    if op == "normalize_whitespace":
        return " ".join(value.split())
    if op == "slice":
        return value[slice(*args)]
    if op == "tail":
        return value[-args[0] :] if args[0] else ""
    if op == "len":
        return len(value)
    result = getattr(value, op)(*args)
    return list(result) if isinstance(result, tuple) else result


def _list_scoped(op, values, fn, options):
    if op == "map":
        return output_value([fn(v) for v in values])
    if op == "filter":
        return [v for v in values if fn(v)]
    if op == "flat_map":
        return output_value([x for v in values for x in _list(fn(v))])
    if op == "any":
        return any(fn(v) for v in values)
    if op == "all":
        return all(fn(v) for v in values)
    if op == "count_where":
        return sum(bool(fn(v)) for v in values)
    if op == "sort_by":
        return sorted(values, key=fn, reverse=options.get("reverse", False))
    raise TypeError(op)


def _list_op(op, value, args, options):
    if op.startswith("python_"):
        return _list_scoped(op[7:], value, args[0], options)
    if op == "len":
        return len(value)
    if op == "slice":
        return value[slice(*args)]
    if op == "tail":
        return value[-args[0] :] if args[0] else []
    if op == "contains":
        return args[0] in value
    if op == "flatten":
        from .eval import _flatten_value

        return _flatten_value(value, args[0])
    if op == "drop_nulls":
        return [v for v in value if v is not None]
    if op == "unique":
        return _unique(value)
    if op == "sort":
        return sorted(value, reverse=options.get("reverse", False))
    if op == "reverse":
        return value[::-1]
    if op in ("sum", "any", "all"):
        return getattr(builtins, op)(value)
    if op in ("min", "max"):
        return getattr(builtins, op)(value) if value else None
    if op == "mean":
        return sum(value) / len(value) if value else None
    if op == "reduce":
        return (
            reduce(args[0], value)
            if args[1] is MISSING
            else reduce(args[0], value, args[1])
        )
    if op == "concat":
        return value + [x for other in args for x in _list(other)]
    if op == "append":
        return output_value([*value, args[0]])
    if op == "prepend":
        return output_value([args[0], *value])
    if op == "zip":
        return [list(v) for v in zip(value, *map(_list, args))]
    if op == "enumerate":
        return [list(v) for v in enumerate(value, args[0])]
    if op == "chunk":
        if type(args[0]) is not int or args[0] < 1:
            raise ValueError("chunk size must be positive")
        return [value[i : i + args[0]] for i in range(0, len(value), args[0])]
    if op == "join":
        return args[0].join(value)
    if op == "union":
        return _unique(value + _list(args[0]))
    if op == "intersection":
        return _unique([v for v in value if v in _list(args[0])])
    if op == "difference":
        return _unique([v for v in value if v not in _list(args[0])])
    raise TypeError(op)


def _object(op, value, args, options):
    if not isinstance(value, dict):
        raise TypeError("Expected object")
    if op == "keys":
        return list(value)
    if op == "values":
        return list(value.values())
    if op == "entries":
        return [[k, v] for k, v in value.items()]
    if op == "pick":
        return {k: v for k, v in value.items() if k in args}
    if op == "omit":
        return {k: v for k, v in value.items() if k not in args}
    if op == "rename":
        result = {}
        for k, v in value.items():
            dest = args[0].get(k, k)
            if dest in result:
                raise ValueError(f"Duplicate object key: {dest}")
            result[dest] = v
        return result
    if op == "merge":
        other = args[0]
        if not isinstance(other, dict):
            raise TypeError("Expected object")
        if options["conflicts"] == "raise" and value.keys() & other.keys():
            raise ValueError("Object merge conflict")
        return other | value if options["conflicts"] == "left" else value | other
    raise TypeError(op)


_NUMERIC = dict(
    abs=abs,
    round=round,
    floor=math.floor,
    ceil=math.ceil,
    sqrt=math.sqrt,
    log=math.log,
    exp=math.exp,
    is_finite=math.isfinite,
    is_nan=math.isnan,
    clip=lambda v, a, b: min(max(v, a), b),
    sign=lambda v: (v > 0) - (v < 0),
    neg=lambda v: -v,
    pos=lambda v: +v,
    floordiv=lambda a, b: a // b,
    mod=lambda a, b: a % b,
    pow=lambda a, b: a**b,
)


_NO_PENDING = builtins.object()


class When:
    def __init__(self, clauses=(), pending=_NO_PENDING):
        self._clauses, self._pending = clauses, pending

    def then(self, value):
        if self._pending is _NO_PENDING:
            raise TypeError("Call when() before then()")
        return When((*self._clauses, self._pending, value))

    def when(self, pred):
        if self._pending is not _NO_PENDING:
            raise TypeError("Missing then()")
        return When(self._clauses, pred)

    def otherwise(self, value):
        if self._pending is not _NO_PENDING:
            raise TypeError("Missing then()")
        return node("when", *self._clauses, value)


class Match:
    def __init__(self, value, clauses=()):
        self._value, self._clauses = value, clauses

    def case(self, value, result):
        from .ast import _wrap

        return Match(self._value, (*self._clauses, _wrap(self._value) == value, result))

    def otherwise(self, value):
        return node("when", *self._clauses, value)


def lit(value):
    from .ast import Lit

    return Lit(value)


def field(path):
    from .ast import Path

    return Path(path)


def item(name="item"):
    from .ast import Item

    return Item(name)


def all_of(*predicates):
    from .ast import _wrap

    return (
        reduce(lambda a, b: a & _wrap(b), predicates[1:], _wrap(predicates[0]))
        if predicates
        else lit(True)
    )


def any_of(*predicates):
    from .ast import _wrap

    return (
        reduce(lambda a, b: a | _wrap(b), predicates[1:], _wrap(predicates[0]))
        if predicates
        else lit(False)
    )


def not_(predicate):
    from .ast import _wrap

    return ~_wrap(predicate)


def object_(**fields):
    return node("object", *fields.values(), keys=tuple(fields))


def array(*values):
    return node("array", *values)


def concat_str(*values, sep=""):
    return node("concat_str", *(values or ("",)), sep=sep)


def format_str(template, *values):
    return node("format_str", template, *values)


def when(predicate):
    return When(pending=predicate)


def match(value):
    return Match(value)


def coalesce(*values):
    if not values:
        raise ValueError("coalesce requires values")
    return node("coalesce", *values)
