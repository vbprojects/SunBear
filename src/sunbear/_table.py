"""Explicit global operations and bounded collection terminals."""

from dataclasses import dataclass
import heapq
import itertools
import copy
from ._fluent import Fluent
from .expr.ast import Expr, Path, _wrap
from .expr.eval import compile
from .expr._sugar import SortKey
from .paths import MISSING
from .record import _freeze


@dataclass(frozen=True)
class Aggregation:
    operation: str
    value: object = None

    def evaluate(self, records):
        if self.operation == "count":
            return len(records)
        fn = compile(_wrap(self.value))
        values = [fn(r) for r in records]
        values = [v for v in values if v is not None and v is not MISSING]
        if self.operation == "sum":
            return sum(values)
        if self.operation == "mean":
            return sum(values) / len(values) if values else None
        if self.operation == "min":
            return min(values) if values else None
        if self.operation == "max":
            return max(values) if values else None
        if self.operation == "collect":
            return values
        raise TypeError("Unknown aggregation")


def count_rows():
    return Aggregation("count")


def sum_(value):
    return Aggregation("sum", value)


def mean(value):
    return Aggregation("mean", value)


def min_(value):
    return Aggregation("min", value)


def max_(value):
    return Aggregation("max", value)


def collect_list(value):
    return Aggregation("collect", value)


def _key(value):
    return compile(value if isinstance(value, Expr) else Path(value))


class TreeMethods(Fluent):
    def first(self, default=None):
        return next(self.iter_rows(), default)

    def one(self):
        rows = list(itertools.islice(self.iter_rows(), 2))
        if len(rows) != 1:
            raise ValueError(
                f"Expected exactly one row; found {len(rows)}"
                + (" or more" if len(rows) == 2 else "")
            )
        return rows[0]

    def is_empty(self):
        return not self.peek(1)

    def preview(self, n=5):
        return self.peek(n)

    def to_columns(self):
        rows = self.collect()
        keys = dict.fromkeys(k for row in rows for k in row)
        return {key: [row.get(key, MISSING) for row in rows] for key in keys}

    def iter_batches(self, size=1000):
        if type(size) is not int or size < 1:
            raise ValueError("Batch size must be positive")

        def batches():
            rows = self.iter_rows()
            while True:
                batch = list(itertools.islice(rows, size))
                if not batch:
                    break
                yield batch

        return batches()

    def write_jsonl(self, path):
        from .io import write_jsonl

        return write_jsonl(self, path)

    def count_rows(self):
        return sum(1 for _ in self.scan())

    def unique_by(self, *keys):
        functions = [_key(key) for key in keys]

        def rows():
            seen = set()
            for record, meta in self.scan():
                key = _freeze(
                    [fn(record) for fn in functions] if functions else record.data
                )
                if key not in seen:
                    seen.add(key)
                    yield record, meta

        return self._derive(rows)

    def order_by(self, *keys):
        if not keys:
            raise ValueError("order_by requires keys")
        specs = [key if isinstance(key, SortKey) else SortKey(key) for key in keys]
        functions = [(_key(spec.value), spec.descending) for spec in specs]

        def rows():
            result = list(self.scan())
            for fn, reverse in reversed(functions):
                result.sort(key=lambda pair: fn(pair[0]), reverse=reverse)
            yield from result

        return self._derive(rows)

    def top_k(self, k, by, *, largest=True):
        if type(k) is not int or k < 0:
            raise ValueError("k must be nonnegative")
        fn = _key(by)

        def rows():
            if k:
                yield from (heapq.nlargest if largest else heapq.nsmallest)(
                    k, self.scan(), key=lambda pair: fn(pair[0])
                )

        return self._derive(rows)

    def value_counts(self, field, *, name="count"):
        return self.group_by(field).agg(**{name: count_rows()})

    def agg(self, **aggregations):
        _validate_aggregations(aggregations)
        from .tree import DataTree

        records = [r for r, _ in self.scan()]
        return DataTree.from_records(
            [{k: agg.evaluate(records) for k, agg in aggregations.items()}]
        )


def _validate_aggregations(aggregations):
    if not aggregations or not all(
        isinstance(a, Aggregation) for a in aggregations.values()
    ):
        raise TypeError("agg requires named aggregation expressions")
    for agg in aggregations.values():
        if agg.operation != "count":
            compile(_wrap(agg.value))


def grouped_aggregate(tree, aggregations):
    _validate_aggregations(aggregations)
    from .tree import DataTree

    if "k" in aggregations:
        raise ValueError("k is reserved for the group key")
    return DataTree.from_records(
        [
            {
                "k": row["k"],
                **{
                    key: agg.evaluate(row["members"])
                    for key, agg in aggregations.items()
                },
            }
            for row in tree.iter_rows()
        ]
    )


def concat(*trees):
    from .tree import DataTree

    if not trees:
        return DataTree.from_records([])
    result = trees[0]
    for tree in trees[1:]:
        result = result + tree
    return result
