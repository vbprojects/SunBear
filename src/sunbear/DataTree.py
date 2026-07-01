"""DataTree.py — iterator-native, no invertibility, plan-aware row table.

Layering:
- Lazy primitives (map/filter/branch_map/insert/take/...) return iterators.
- Inter-record ops (group_by/join/reduce/reduce_by/sort_by) materialize via
  the Plan layer, which builds an index of record references with cardinality
  detection (1:1, 1:N, N:1, N:M).

NO invertibility: no _history, no undo closures, no provenance markers.
Records are mutable and shared by reference (per design decision).
"""
from __future__ import annotations
import copy
import itertools
from typing import Any, Callable, Iterable, Iterator, List, Tuple

from .Record import Record, _freeze

# Twig: (Record, meta). Re-export for callers that want the type alias.
Twig = Tuple[Record, dict]

# Sentinel for "init not provided" in reduce / reduce_by.
_SENTINEL = object()
# ═══════════════════════════════════════════════════════════════════════════
# Plan — inter-record index with cardinality detection
# ═══════════════════════════════════════════════════════════════════════════

class Plan:
    """An index built from a materialized stream.

    Holds record **references** (no copies). Keys are frozen.
    Detects cardinality during build by sampling the first N rows.

    Cardinality tags:
      "1:1"  — every key is unique on both sides
      "1:N"  — left keys unique, right keys repeated (or vice versa, by tag)
      "N:1"  — symmetric; planner chooses which side to index
      "N:M"  — both sides have repeated keys
    """

    SAMPLE_SIZE = 64

    def __init__(self, key, index: dict, order: list, cardinality: str,
                 side: str = "left"):
        self.key = key
        self.index = index        # dict[frozen_key, list[Record]]
        self.order = order        # list of keys in first-seen order
        self.cardinality = cardinality
        self.side = side          # "left" or "right"

    def explain(self) -> str:
        n_keys = len(self.index)
        n_rows = sum(len(v) for v in self.index.values())
        avg = n_rows / n_keys if n_keys else 0
        return (f"Plan(key={self.key!r}, cardinality={self.cardinality}, "
                f"side={self.side}, keys={n_keys}, rows={n_rows}, "
                f"avg_per_key={avg:.2f})")

    def execute(self) -> list:
        """Materialize as a list of ``{"k": key, "members": [records]}``."""
        return [{"k": k, "members": self.index[k]} for k in self.order]

    @classmethod
    def build(cls, rows: Iterable[Twig], key_fn: Callable[[Record, dict], Any],
              side: str = "left",
              sample_size: int | None = None) -> "Plan":
        """Build an index from an iterable of (record, meta).

        Samples ``sample_size`` rows for cardinality detection, then indexes
        the rest. Returns a Plan whose ``.index`` is the full materialized map.
        """
        sample_n = sample_size if sample_size is not None else cls.SAMPLE_SIZE
        sample_keys: list = []
        index: dict = {}
        order: list = []
        seen: set = set()

        # single pass: collect sample + build index
        for r, m in rows:
            k = key_fn(r, m)
            if len(sample_keys) < sample_n:
                sample_keys.append(k)
            if k in seen:
                index[k].append(r)
            else:
                seen.add(k)
                order.append(k)
                index[k] = [r]

        # detect cardinality from sample
        cardinality = _detect_cardinality(sample_keys)
        return cls(key=key_fn, index=index, order=order,
                   cardinality=cardinality, side=side)


def _detect_cardinality(sample_keys: list) -> str:
    """Classify sample as 1:1 / 1:N / N:M.

    With a sample we can't tell which side is which; we use N:M as the default
    for ambiguous cases and rely on the caller (join) to refine via direction.
    """
    if not sample_keys:
        return "1:1"
    n_unique = len(set(sample_keys))
    n = len(sample_keys)
    if n_unique == n:
        return "1:1"
    if n_unique == 1:
        return "N:M"
    # Heuristic: if any key appears > 2×, treat as N:M; otherwise ambiguous
    from collections import Counter
    counts = Counter(sample_keys)
    if max(counts.values()) >= 3:
        return "N:M"
    return "N:M"


# ═══════════════════════════════════════════════════════════════════════════
# DataTree
# ═══════════════════════════════════════════════════════════════════════════

class DataTree:
    """Iterator-native, row-based table.

    Construction accepts any iterable (list, generator, sequence). All
    lazy primitives (map/filter/branch_map/insert/take) return generators
    that are NOT cached — each traversal re-runs upstream ops.
    """

    def __init__(self, rows: Iterable[Twig]):
        # DO NOT eagerly materialize. Store the iterable as-is.
        self._rows = rows

    # ---- constructors ----

    @classmethod
    def from_records(cls, records) -> "DataTree":
        """Construct from a list of dicts. Eagerly materialized (re-traversable)."""
        rows = [(Record(dict(r), {"i": i}), {"i": i})
                for i, r in enumerate(records)]
        return cls(rows)

    @classmethod
    def from_iter(cls, it: Iterable[dict]) -> "DataTree":
        """Stream from any iterable of dicts. Single-pass (consumed on scan).

        Use ``from_records`` for re-traversable streams.
        """
        counter = itertools.count()
        def gen():
            for r in it:
                i = next(counter)
                yield Record(dict(r), {"i": i}), {"i": i}
        return cls(gen())

    # ---- iteration ----

    def __iter__(self) -> Iterator[Twig]:
        return iter(self._rows)

    def scan(self):
        """Alias for __iter__ — yields fresh (Record, meta) tuples."""
        return iter(self._rows)

    def _materialize(self) -> list:
        """Single explicit materialization point. Caches result on self."""
        if not isinstance(self._rows, list):
            self._rows = list(self._rows)
        return self._rows

    def __len__(self) -> int:
        materialized = self._materialize()
        return len(materialized)

    def __bool__(self) -> bool:
        self._materialize()
        return bool(self._rows)

    # ---- terminal extractors ----

    def collect(self) -> list:
        """Drain the iterator into a list of plain data dicts."""
        return [r.data for r, _ in self.scan()]

    def pluck(self, indexer) -> list:
        """Extract a single column as a list."""
        ix = Record.resolve(indexer)
        return [r.get(indexer) for r, _ in self.scan()]

    def inspect(self, indexer):
        """Return the inferred Schema of values at *indexer* across all rows.

        The returned Schema is named after the indexer for display purposes.
        Supports all Record indexer types: str, dotted-str, tuple, list, dict.
        Also accepts Path/Col nodes from the expr layer.

        Examples
        --------
        >>> t = DataTree.from_records([{"a": 1}, {"a": "hi"}])
        >>> t.inspect("a")
        Schema(name='a', (a=Union[int, str]))
        """
        from .Schema import (
            Schema, SchemaList, Branch, Leaf, infer_schema,
            reconcile as _reconcile,
        )

        # Normalize expr nodes (Path/Col) to their raw indexer string
        raw = getattr(indexer, "indexer", None)
        if raw is not None and isinstance(raw, str):
            indexer = raw

        # Build a display name for the indexer
        if isinstance(indexer, str):
            display_name = indexer
        elif isinstance(indexer, (list, tuple)):
            display_name = "[" + ", ".join(str(i) for i in indexer) + "]"
        elif isinstance(indexer, dict):
            display_name = "{" + ", ".join(str(k) for k in indexer.keys()) + "}"
        else:
            display_name = str(indexer)

        # Extract values from all rows at the given indexer
        values = []
        for r, _ in self.scan():
            try:
                v = r.get(indexer)
                values.append(v)
            except (KeyError, TypeError):
                values.append(None)

        if not values:
            return Schema(Branch({}), name=display_name)

        # Infer schemas from each extracted value
        branches: List[Branch] = []
        for v in values:
            node = infer_schema(v)
            if isinstance(node, Branch):
                branches.append(node)
            elif isinstance(node, Leaf):
                scalar_name = display_name.rpartition(".")[2] or display_name
                branches.append(Branch({scalar_name: node}))

        if not branches:
            return Schema(Branch({}), name=display_name)

        try:
            reconciled = _reconcile(branches)
            return Schema(reconciled, name=display_name)
        except ValueError:
            unique_schemas = []
            for b in branches:
                if b not in unique_schemas:
                    unique_schemas.append(b)
            return SchemaList([
                Schema(b, name=f"{display_name} (variant {i})")
                for i, b in enumerate(unique_schemas)
            ])

    def rows(self, **aliases) -> list:
        """Row-wise extraction: ``[{alias: value, ...}, ...]``."""
        out = []
        for r, _ in self.scan():
            out.append({a: r.get(k) for a, k in aliases.items()})
        return out

    def col(self, **aliases) -> dict:
        """Columnar extraction: ``{alias: [values...]}``."""
        cols = {a: [] for a in aliases}
        for r, _ in self.scan():
            for a, ix in aliases.items():
                cols[a].append(r.get(ix))
        return cols
    
    # ---- terminal iterators (yield data) ----
    
    def iterrows(self, **aliases) -> Iterator[dict]:
        """Yield each row as a plain dict."""
        for r, _ in self.scan():
            yield {a: r.get(k) for a, k in aliases.items()}
    
    def itercols(self, **aliases) -> Iterator[dict]:
        """Yield each column as a list."""
        for a, k in aliases.items():
            yield {a: [r.get(k) for r, _ in self.scan()]}
    
    def iterpluck(self, indexer) -> Iterator[Any]:
        """Yield each value in a single column."""
        for r, _ in self.scan():
            yield r.get(indexer)
    
    def itercollect(self) -> Iterator[dict]:
        """Yield each row as a plain dict."""
        for r, _ in self.scan():
            yield dict(r.data)
    
    ipluck = iterpluck
    icollect = itercollect
    irows = iterrows
    icols = itercols

    # ---- LAZY primitives (return generators) ----

    def map(self, fn: Callable[[Record], Record]) -> "DataTree":
        """Whole-record map. Yields ``fn(r)`` per row. No snapshot."""
        def gen():
            for r, m in self.scan():
                yield fn(r), m
        return DataTree(gen())

    def filter(self, pred: Callable[[Record, dict], bool]) -> "DataTree":
        """Record-level filter. Yields rows where pred is True."""
        def gen():
            for r, m in self.scan():
                if pred(r, m):
                    yield r, m
        return DataTree(gen())

    def branch_map(self, roots, fn: Callable[[Record], None]) -> "DataTree":
        """Apply ``fn(record)`` to each row in-place on a shallow copy.

        ``roots`` is an iterable of top-level field names that ``fn`` may
        touch — used by callers like ``set``/``move`` to know which branches
        to copy. For the lazy backbone we copy the whole data dict (cheap,
        and records are mutable per design).
        """
        roots = list(roots) if roots else None
        def gen():
            for r, m in self.scan():
                if roots is None:
                    new = Record(dict(r.data), dict(m))
                else:
                    # shallow copy each declared root, leave others shared
                    new_data = {}
                    for k, v in r.data.items():
                        if k in roots:
                            new_data[k] = copy.copy(v)
                        else:
                            new_data[k] = v
                    new = Record(new_data, dict(m))
                fn(new)
                yield new, m
        return DataTree(gen())

    def insert(self, rows: Iterable[Twig]) -> "DataTree":
        """Append rows from any iterable. Chained lazy."""
        return DataTree(itertools.chain(self.scan(), rows))

    def take(self, start: int = 0, stop: int | None = None) -> "DataTree":
        """Slice by position. Equivalent to ``itertools.islice``."""
        return DataTree(itertools.islice(self.scan(), start, stop))

    def head(self, n: int = 5) -> "DataTree":
        return self.take(0, n)

    def explode(self, indexer) -> "DataTree":
        """Explode a list field into one row per element.

        For each row, the value at *indexer* is replaced by each of its
        elements in turn, producing N output rows for a list of length N.
        All other fields are shallow-copied per output row.  Non-list values
        pass through unchanged.

        Parameters
        ----------
        indexer : Any
            Any value accepted by ``Record.resolve`` (dotted string, dict,
            tuple, list, or expr ``Path``/``Col``).

        Returns
        -------
        DataTree
            A new lazy DataTree (generator-backed).

        Examples
        --------
        >>> dt = DataTree.from_records([
        ...     {"name": "Alice", "tags": ["a", "b"]},
        ...     {"name": "Bob",   "tags": ["c"]},
        ... ])
        >>> dt.explode("tags").collect()
        [{'name': 'Alice', 'tags': 'a'}, {'name': 'Alice', 'tags': 'b'}, {'name': 'Bob', 'tags': 'c'}]
        """
        ix = Record.resolve(indexer)
        root = next(iter(ix)) if ix else None
        roots = [root] if root else None

        def gen():
            for r, m in self.scan():
                val = r.get(indexer)
                if isinstance(val, list):
                    for elem in val:
                        # Deep-copy the branch containing the list so that
                        # nested dicts (e.g. profile.emails) are not shared
                        # across iterations.
                        new_data = copy.deepcopy(r.data)
                        Record._walk(new_data, ix, "set", elem)
                        yield Record(new_data, dict(m)), dict(m)
                else:
                    yield Record(dict(r.data), dict(m)), dict(m)

        return DataTree(gen())

    def tail(self, n: int = 5) -> "DataTree":
        """Last n rows — needs full materialization."""
        materialized = self._materialize()
        return DataTree(materialized[-n:] if n > 0 else [])

    # ---- invertible-feeling sugar (now plain wrappers, no undo) ----

    def apply(self, fn: Callable[[Record], Record]) -> "DataTree":
        return self.map(fn)

    def keep(self, pred: Callable[[Record, dict], bool]) -> "DataTree":
        return self.filter(pred)

    def assign_at(self, path, fn: Callable[[Record], Any]) -> "DataTree":
        """Set ``fn(record)`` at ``path`` on every row."""
        ix = Record.resolve(path)
        root = next(iter(ix)) if ix else None
        roots = [root] if root else None
        return self.branch_map(roots, lambda r: r.set(path, fn(r)))

    def set(self, indexer, value) -> "DataTree":
        ix = Record.resolve(indexer)
        roots = list(ix.keys())
        return self.branch_map(roots, lambda r: r.set(indexer, value))

    def add(self, indexer, value) -> "DataTree":
        ix = Record.resolve(indexer)
        roots = list(ix.keys())
        def fn(r):
            if r.get(indexer) is None:
                r.set(indexer, value)
        return self.branch_map(roots, fn)

    def move(self, src, dst) -> "DataTree":
        s, d = Record.resolve(src), Record.resolve(dst)
        return self.branch_map(list(s) + list(d), lambda r: r.mv(src, dst))

    def copy(self, src, dst) -> "DataTree":
        s, d = Record.resolve(src), Record.resolve(dst)
        return self.branch_map(list(s) + list(d), lambda r: r.cpy(src, dst))

    def drop(self, *indexers) -> "DataTree":
        """Remove fields by path."""
        resolved = [Record.resolve(ix) for ix in indexers]
        roots = list({k for ix in resolved for k in ix.keys()})
        def fn(r):
            for ix in resolved:
                r._walk(r.data, ix, "delete")
        return self.branch_map(roots, fn)

    def rename(self, **mapping) -> "DataTree":
        """Rename fields: ``tree.rename(old_name="new_name")``."""
        t = self
        for src, dst in mapping.items():
            t = t.move(src, dst)
        return t

    # ---- TERMINAL inter-record ops (materialize + plan) ----

    def group_by(self, key, *reduce_fns) -> "DataTree":
        """Group rows by ``key`` (indexer or callable).

        Returns a new DataTree with one row per key. If ``reduce_fns`` are
        given, each is called as ``fn([records])`` per group; the resulting
        values are stored under ``"v"`` (single fn) or ``"v_0"``, ``"v_1"``...
        """
        keyfn = key if callable(key) else (
            lambda r, m, _ix=Record.resolve(key): _freeze(r.get(_ix))
        )
        plan = Plan.build(self.scan(), keyfn, side="left")
        rows = []
        for k in plan.order:
            members = plan.index[k]
            if reduce_fns:
                if len(reduce_fns) == 1:
                    rows.append({"k": k, "v": reduce_fns[0](members)})
                else:
                    out = {"k": k}
                    for i, fn in enumerate(reduce_fns):
                        out[f"v_{i}"] = fn(members)
                    rows.append(out)
            else:
                rows.append({"k": k, "members": members})
        return DataTree.from_records(rows)

    def join(self, right, on, how: str = "inner") -> "DataTree":
        """Join with a list of right-side dicts on field ``on``.

        Builds an index over ``right`` (smaller side assumption) and streams
        the left rows. Records are merged by reference where possible.
        """
        # build right index
        right_plan = Plan.build(
            ((Record(dict(r), {}), {}) for r in right),
            lambda r, m: _freeze(r.get(on)),
            side="right",
        )
        out: list = []
        for lr, lm in self.scan():
            lk = _freeze(lr.get(on))
            matches = right_plan.index.get(lk, [])
            if not matches:
                if how != "inner":
                    out.append(dict(lr.data))
                continue
            for rr in matches:
                merged = dict(lr.data)
                for rk, rv in rr.data.items():
                    if rk not in merged:
                        merged[rk] = rv
                out.append(merged)
        return DataTree.from_records(out)

    def reduce(self, fn: Callable[[Any, Record], Any], init=_SENTINEL):
        """Terminal fold over rows.

        ``init`` is required if the stream might be empty. Without ``init``,
        the first record's data is used as the seed (so ``fn(acc, r)``
        receives ``r.data`` first, not ``r``).

        Returns the accumulated value.
        """
        if init is _SENTINEL:
            it = iter(self.scan())
            try:
                first_r, _ = next(it)
            except StopIteration:
                raise ValueError("reduce() of empty stream with no init")
            acc = first_r.data
            for r, _ in it:
                acc = fn(acc, r)
            return acc
        acc = init
        for r, _ in self.scan():
            acc = fn(acc, r)
        return acc

    def reduce_by(self, key, fn: Callable[[Any, Record], Any], init=_SENTINEL) -> "DataTree":
        """Group + reduce in a single pass. Returns ``DataTree`` of (key, value).

        Without ``init``, the first record's data is used as the seed per group.
        """
        keyfn = key if callable(key) else (
            lambda r, m, _ix=Record.resolve(key): _freeze(r.get(_ix))
        )
        accumulators: dict = {}
        order: list = []
        seen: set = set()
        for r, m in self.scan():
            k = keyfn(r, m)
            if k in seen:
                accumulators[k] = fn(accumulators[k], r)
            else:
                seen.add(k)
                order.append(k)
                accumulators[k] = r.data if init is _SENTINEL else fn(init, r)
        rows = [{"k": k, "v": accumulators[k]} for k in order]
        return DataTree.from_records(rows)

    def sort_by(self, indexer, reverse: bool = False) -> "DataTree":
        """Full materialize + sort by the value at ``indexer``."""
        ix = Record.resolve(indexer)
        materialized = self._materialize()
        sorted_rows = sorted(
            materialized, key=lambda t: _freeze(t[0].get(ix)), reverse=reverse
        )
        return DataTree(sorted_rows)

    # ---- introspection ----

    @property
    def schema(self):
        """Infer schema by materializing and reconciling all records.

        Lazy DataTrees are drained on access. Result is a Schema instance.
        """
        from .Schema import Schema, infer_schema, reconcile, Branch as _Branch
        materialized = self.collect()
        if not materialized:
            return Schema(_Branch({}))
        branches = []
        for rec in materialized:
            node = infer_schema(rec)
            if isinstance(node, _Branch):
                branches.append(node)
        if not branches:
            return Schema(_Branch({}))
        return Schema(reconcile(branches))

    def plan(self, key, side: str = "left") -> Plan:
        """Build a Plan object explicitly (for callers who want .explain())."""
        keyfn = key if callable(key) else (
            lambda r, m, _ix=Record.resolve(key): _freeze(r.get(_ix))
        )
        return Plan.build(self.scan(), keyfn, side=side)

    # ---- expr driver ----

    def expr(self, *statements) -> "DataTree":
        """Apply expr statements (tuples) to this DataTree.

        Usage::

            dt.expr(
                assign(b.normalized_age, (b.age - mu) / std),
                keep(b.normalized_age < 50),
            )
        """
        from .expr.lower import run_expr
        return run_expr(self, *statements)

    # ---- operator overloading ----

    def __add__(self, other) -> "DataTree":
        if isinstance(other, DataTree):
            return self.insert(other.scan())
        return self.insert(DataTree.from_records(other).scan())

    def __or__(self, fn) -> "DataTree":
        """Pipe: ``dt | func`` → ``func(dt)``."""
        if callable(fn):
            return fn(self)
        return NotImplemented

