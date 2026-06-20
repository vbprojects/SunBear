"""datatree.py — invertible, row-based DataTree satisfying L1/L2."""
from __future__ import annotations
import copy
from typing import Any, Callable, List, Tuple

try:
    from .Record import (
        Record,
        _MISSING,
        _Missing,
        _deep_merge,
        _freeze,
        construct_schema,
    )
except ImportError:
    from Record import (  # type: ignore[no-redef]
        Record,
        _MISSING,
        _Missing,
        _deep_merge,
        _freeze,
        construct_schema,
    )

try:
    from .Schema import Schema, SchemaList, infer_schema, Branch, Leaf, reconcile as _reconcile
except ImportError:
    from Schema import Schema, infer_schema, Branch, Leaf, SchemaList  # type: ignore[no-redef]
    from Schema import reconcile as _reconcile  # type: ignore[no-redef]

_INS = "_ins"          # reserved provenance marker for insertion
_UNDO = "_undo"        # reserved per-row complement for row maps


Twig  = Tuple[Record, dict]
State = List[Twig]
Undo  = Callable[[State], State]   # post-state -> pre-state


def _clone(state: State) -> State:
    return [(Record(copy.deepcopy(r.data)), dict(m)) for r, m in state]


class DataTree:
    """
    Immutable, re-iterable, row-based table.

    Backend: a materialized snapshot `_twigs`. `scan()` hands out a fresh
    iterator each call (thread-safe by immutability), satisfying the
    "thread-safe reiterable iterator" requirement.

    Invertibility: every transform appends a *backward closure* (carrying a
    minimal complement) to `_history`. `invert()` pops one; `invert_all()`
    unwinds the whole pipeline — making transitive reachability constructive.
    """

    def __init__(self, twigs: State, history: Tuple[Undo, ...] = (), track = True):
        self._twigs: State = _clone(twigs)
        self._history: Tuple[Undo, ...] = tuple(history)
        self._track = track

    # -- backend ---------------------------------------------------------
    @classmethod
    def from_records(cls, records) -> "DataTree":
        return cls([(Record(dict(r)), {"index": i})
                    for i, r in enumerate(records)])

    @property
    def schema(self) -> Schema:
        """Return the inferred schema for all current twigs."""
        return Schema.from_records([r.data for r, _ in self._twigs])

    @property
    def twigs(self) -> State:
        return _clone(self._twigs)                  # defensive copy

    def scan(self):
        return iter(self.twigs)                      # fresh, independent

    __iter__ = scan

    # -- inversion machinery --------------------------------------------
    def _step(self, new_twigs, backward):
        if not self._track:
            return DataTree(new_twigs, (), track=False)      # backward dropped → never retained
        return DataTree(new_twigs, self._history + (backward,), track=True)
    
    def untracked(self):
        return DataTree(self.twigs, (), track=False)          # opt out from here on

    @property
    def last_undo(self) -> Undo:
        return self._history[-1]

    def invert(self) -> "DataTree":
        """Undo the most recent operation."""
        *rest, back = self._history
        return DataTree(back(self.twigs), tuple(rest))

    def invert_all(self) -> "DataTree":
        """Unwind the entire pipeline back to the source state."""
        t = self
        while t._history:
            t = t.invert()
        return t

    # === operator classes ==============================================

    # 1. Row map (1->1, self-dual). Complement = old value per row.
    def map_set(self, key: str, value: Any) -> "DataTree":
        new = [(Record({**r.data, key: value}),
                {**m, _UNDO: r.data.get(key, _MISSING)})
               for r, m in self._twigs]

        def back(post: State) -> State:
            out = []
            for r, m in post:
                old = m[_UNDO]
                d = dict(r.data)
                d.pop(key, None) if old is _MISSING else d.__setitem__(key, old)
                out.append((Record(d), {k: v for k, v in m.items() if k != _UNDO}))
            return out
        return self._step(new, back)

    # 2. Filter (1->{0,1}). Complement = dropped rows + original indices.
    def filter(self, pred: Callable[[Record, dict], bool]) -> "DataTree":
        kept, dropped = [], []
        for i, (r, m) in enumerate(self._twigs):
            (kept.append((r, m)) if pred(r, m) else dropped.append((i, (r, m))))

        def back(post: State) -> State:
            out = list(post)
            for i, twig in dropped:                  # ascending i -> exact re-insertion
                out.insert(i, twig)
            return out
        return self._step(kept, back)

    # 3. Insertion. Complement = provenance marker; inverse is a filter.
    def insert(self, new_rows: State) -> "DataTree":
        tagged = [(r, {**m, _INS: True}) for r, m in new_rows]

        def back(post: State) -> State:
            return [(r, m) for r, m in post if not m.get(_INS)]
        return self._step(self.twigs + tagged, back)

    # 4. Explode (1->n). Inverse = group + reassemble (n->1).
    def explode(self, key: str) -> "DataTree":
        new, comp = [], []
        for r, m in self._twigs:
            pidx = m["index"]
            base = {k: v for k, v in r.data.items() if k != key}
            comp.append((pidx, base, dict(m)))       # parent skeleton (handles empties)
            for pos, v in enumerate(list(r.data.get(key, []))):
                new.append((Record({**base, key: v}),
                            {**m, "parent": pidx, "pos": pos}))

        def back(post: State) -> State:
            groups: dict = {}
            for r, m in post:
                groups.setdefault(m["parent"], []).append((m["pos"], r.data[key]))
            return [(Record({**base, key: [v for _, v in sorted(groups.get(p, []))]}),
                     pmeta) for p, base, pmeta in comp]
        return self._step(new, back)

    # 6. Join (n->m). Inverse = join (m->n). Complement = unmatched-left rows.
    def join(self, right: List[dict], on: str, right_cols: List[str]) -> "DataTree":
        rindex: dict = {}
        for rr in right:
            rindex.setdefault(rr[on], []).append(rr)
        new, unmatched = [], []
        for r, m in self._twigs:
            matches = rindex.get(r.data.get(on), [])
            if not matches:                                # totality: stash dropped rows
                unmatched.append((m["index"], (r, m))); continue
            for rr in matches:
                new.append((Record({**r.data, **{c: rr[c] for c in right_cols}}),
                            {**m, "_src": m["index"]}))     # provenance

        def back(post: State) -> State:
            seen: dict = {}
            for r, m in post:
                li = m["_src"]
                if li in seen:                              # collapse fan-out
                    continue
                seen[li] = (Record({k: v for k, v in r.data.items()
                                    if k not in right_cols}),
                            {k: v for k, v in m.items() if k != "_src"})
            out = list(seen.values()) + [t for _, t in unmatched]
            out.sort(key=lambda t: t[1]["index"])
            return out
        return self._step(new, back)

    def __len__(self):
        return len(self._twigs)

    # ---- positional sugar: head / take / slicing (invertible filters) ----
    def take(self, start: int = 0, stop: int | None = None) -> "DataTree":
        stop = len(self._twigs) if stop is None else stop
        kept, dropped = [], []
        for i, (r, m) in enumerate(self._twigs):
            (kept if start <= i < stop else None)
            if start <= i < stop:
                kept.append((r, m))
            else:
                dropped.append((i, (r, m)))
        def back(post):
            out = list(post)
            for i, twig in dropped:           # ascending i -> exact reinsertion
                out.insert(i, twig)
            return out
        return self._step(kept, back)

    def head(self, n: int = 5) -> "DataTree":
        return self.take(0, n)

    def tail(self, n: int = 5) -> "DataTree":
        length = len(self._twigs)
        return self.take(max(0, length - n), length)

    def first(self) -> dict | None:
        """Return the first record's data dict (or None if empty)."""
        return copy.deepcopy(self._twigs[0][0].data) if self._twigs else None

    def last(self) -> dict | None:
        """Return the last record's data dict (or None if empty)."""
        return copy.deepcopy(self._twigs[-1][0].data) if self._twigs else None

    def __getitem__(self, k):
        if isinstance(k, slice):
            return self.take(k.start or 0, k.stop)
        return self._twigs[k]                 # int -> single twig (read-only)

    # ---- python operator overloading ----
    def __add__(self, other: "DataTree | List[dict]") -> "DataTree":
        """Concatenate: tree + other_tree  or  tree + [{'a': 1}]."""
        if isinstance(other, DataTree):
            return self.insert(other.twigs)
        return self.insert(DataTree.from_records(other).twigs)

    def __or__(self, fn: Callable[["DataTree"], "DataTree"]) -> "DataTree":
        """Pipe operator: tree | custom_transform."""
        return fn(self)

    def __bool__(self):
        """Truthiness: False when empty."""
        return bool(self._twigs)

    # ---- projection: invertible row map (complement = original rows) ----
    def select(self, **aliases) -> "DataTree":
        """Select columns with aliases: tree.select(name="record.age").

        Accepts Symbols/PathBuilders as indexer values.
        """
        try:
            from .expr.namespace import as_indexer
        except ImportError:
            from expr.namespace import as_indexer  # type: ignore[no-redef]
        originals = [copy.deepcopy(r.data) for r, _ in self._twigs]
        new = [(Record({a: r.get_leaves(as_indexer(ix)) for a, ix in aliases.items()}), dict(m))
               for r, m in self._twigs]
        def back(post):
            return [(Record(copy.deepcopy(o)), dict(m))
                    for (r, m), o in zip(post, originals)]
        return self._step(new, back)

    # ---- read-only collectors ----
    def col(self, **aliases) -> dict:
        """Columnar extraction: {alias: [values...]}.

        Accepts Symbols/PathBuilders as indexer values.
        """
        try:
            from .expr.namespace import as_indexer
        except ImportError:
            from expr.namespace import as_indexer  # type: ignore[no-redef]
        cols = {a: [] for a in aliases}
        for r, _ in self._twigs:
            for a, ix in aliases.items():
                cols[a].append(r.get_leaves(as_indexer(ix)))
        return cols

    def collect(self) -> list:
        """Row-wise extraction: list of plain data dicts."""
        return [copy.deepcopy(r.data) for r, _ in self._twigs]

    # ---- semantic aliases ----
    def where(self, pred: Callable[[Record, dict], bool]) -> "DataTree":
        """SQL-like alias for filter."""
        return self.filter(pred)

    def pluck(self, indexer) -> list:
        """Extract a single flattened column as a list."""
        try:
            from .expr.namespace import as_indexer
        except ImportError:
            from expr.namespace import as_indexer  # type: ignore[no-redef]
        alias = "_pluck"
        return self.col(**{alias: as_indexer(indexer)}).get(alias, [])

    def inspect(self, indexer) -> Schema:
        """Return the inferred Schema of values at *indexer* across all twigs.

        The returned Schema is named after the indexer for display purposes.
        Supports all Record indexer types: str, dotted-str, tuple, list, dict.
        Also accepts Symbols (`Sym(...)`) and PathBuilders (`b.foo.bar`).

        Examples
        --------
        >>> t = DataTree.from_records([{"a": 1}, {"a": "hi"}])
        >>> t.inspect("a")
        Schema(name='a', (a=Union[int, str]))
        """
        # Normalize Symbols / PathBuilders to a plain indexer
        try:
            from .expr.namespace import as_indexer
        except ImportError:
            from expr.namespace import as_indexer  # type: ignore[no-redef]
        indexer = as_indexer(indexer)

        # Build a display name for the indexer
        if isinstance(indexer, str):
            display_name = indexer
        elif isinstance(indexer, (list, tuple)):
            display_name = "[" + ", ".join(str(i) for i in indexer) + "]"
        elif isinstance(indexer, dict):
            # Use the top-level keys as the name
            display_name = "{" + ", ".join(str(k) for k in indexer.keys()) + "}"
        else:
            display_name = str(indexer)

        # Extract values from all twigs at the given indexer
        values = []
        for r, _ in self._twigs:
            try:
                # Use r.get() (not get_leaves) to preserve dict structure
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
                # Scalar value — wrap in a single-field Branch.
                # Use the last path segment of a dotted string as the field name,
                # or the display_name for simple strings.
                scalar_name = display_name.rpartition(".")[2] or display_name
                branches.append(Branch({scalar_name: node}))

        if not branches:
            return Schema(Branch({}), name=display_name)

        # Try to reconcile; if it fails due to mismatch, return all unique schemas
        try:
            reconciled = _reconcile(branches)
            return Schema(reconciled, name=display_name)
        except ValueError:
            # Return a list of unique schemas if reconciliation fails
            unique_schemas = []
            for b in branches:
                if b not in unique_schemas:
                    unique_schemas.append(b)
            return SchemaList([Schema(b, name=f"{display_name} (variant {i})") for i, b in enumerate(unique_schemas)])

    # ---- structural sugar (invertible) ----
    def drop(self, *indexers) -> "DataTree":
        """Remove fields by path (invertible)."""
        resolved = [Record._resolve_indexer(ix) for ix in indexers]
        roots = list({k for ix in resolved for k in ix.keys()})

        def _dropper(nr):
            for ix in resolved:
                Record._walk_delete(nr.data, ix)

        return self._branch_map(roots, _dropper)

    def rename(self, **mapping) -> "DataTree":
        """Rename fields: tree.rename(**{'old.path': 'new.path'})."""
        t = self
        for dst, src in mapping.items():
            t = t.move(src, dst)
        return t

    def sort_by(self, indexer, reverse: bool = False) -> "DataTree":
        """Sort rows by a path (invertible)."""
        try:
            from .expr.namespace import as_indexer
        except ImportError:
            from expr.namespace import as_indexer  # type: ignore[no-redef]
        ix = Record._resolve_indexer(as_indexer(indexer))
        new = sorted(
            self._twigs,
            key=lambda t: _freeze(t[0].get_leaves(ix)),
            reverse=reverse,
        )

        def back(post: State) -> State:
            return sorted(post, key=lambda t: t[1].get("index", 0))

        return self._step(new, back)

    # ---- group_by now accepts an indexer OR a callable ----
    def group_by(self, key) -> "DataTree":
        if callable(key):
            keyfn = key
        else:
            try:
                from .expr.namespace import as_indexer
            except ImportError:
                from expr.namespace import as_indexer  # type: ignore[no-redef]
            resolved = Record._resolve_indexer(as_indexer(key))
            keyfn = lambda r, m: _freeze(r.get_leaves(resolved))
        groups, order = {}, []
        for r, m in self._twigs:
            k = keyfn(r, m)
            if k not in groups:
                groups[k] = []; order.append(k)
            groups[k].append({"data": dict(r.data), "metadata": dict(m)})   # dict member
        new = [(Record({"group": k, "members": groups[k]}), {"index": gi})
               for gi, k in enumerate(order)]
        def back(post):
            restored = []
            for r, _m in post:
                for member in r.data["members"]:                            # read dicts
                    restored.append((Record(dict(member["data"])),
                                     dict(member["metadata"])))
            restored.sort(key=lambda t: t[1]["index"])
            return restored
        return self._step(new, back)


    # ---- invertible path mutations (complement = touched top-level branches) ----
    def assign_at(self, path, fn: Callable[[Record], Any]) -> "DataTree":
        """Per-row computed set: assign ``fn(record)`` to ``path`` on every row.

        Builds on ``_branch_map`` — invertible for free (branch snapshot).
        ``path`` is a standard indexer (str, tuple, dotted string).

        If the target path has depth >= 1 (e.g., 'profile.age'), the root is
        extracted and the full path is set inside the row fn.
        """
        ix = Record._resolve_indexer(path)
        roots = list(ix.keys())

        def _setter(nr: Record):
            nr.set(ix, fn(nr))

        return self._branch_map(roots, _setter)

    def apply(self, fn: Callable[[Record], "Record"]) -> "DataTree":
        """Whole-record map: ``fn(Record) -> Record``.

        Complement = full original ``.data`` per row (correct — possibly
        heavy; optimize later if profiling demands).
        """
        snaps = [copy.deepcopy(r.data) for r, _ in self._twigs]
        new = [(fn(Record(copy.deepcopy(r.data))), dict(m))
               for r, m in self._twigs]

        def back(post: State) -> State:
            return [(Record(copy.deepcopy(o)), dict(m))
                    for (_, m), o in zip(post, snaps)]
        return self._step(new, back)

    def keep(self, pred: Callable[[Record, dict], bool]) -> "DataTree":
        """Alias for record-level ``filter`` — the `expr` statement verb."""
        return self.filter(pred)

    def _branch_map(self, roots, transform) -> "DataTree":
        roots = list(roots)
        def _snap(v):
            return _MISSING if v is _MISSING else copy.deepcopy(v)   # preserve identity
        snaps, new = [], []
        for r, m in self._twigs:
            snaps.append({rt: _snap(r.data.get(rt, _MISSING)) for rt in roots})
            nr = Record(copy.deepcopy(r.data)); transform(nr)
            new.append((nr, dict(m)))
        def back(post):
            out = []
            for (r, m), snap in zip(post, snaps):
                d = copy.deepcopy(r.data)
                for rt, val in snap.items():
                    if val is _MISSING:
                        d.pop(rt, None)
                    else:
                        d[rt] = val
                out.append((Record(d), dict(m)))
            return out
        return self._step(new, back)

    def set(self, indexer, value) -> "DataTree":
        ix = Record._resolve_indexer(indexer)
        return self._branch_map(ix.keys(), lambda nr: nr.set(ix, value))

    def add(self, indexer, value) -> "DataTree":
        ix = Record._resolve_indexer(indexer)
        return self._branch_map(ix.keys(), lambda nr: nr.add(ix, value))

    def move(self, src, dst) -> "DataTree":
        s, d = Record._resolve_indexer(src), Record._resolve_indexer(dst)
        return self._branch_map(list(s) + list(d), lambda nr: nr.mv(s, d))

    def copy(self, src, dst) -> "DataTree":
        s, d = Record._resolve_indexer(src), Record._resolve_indexer(dst)
        return self._branch_map(list(s) + list(d), lambda nr: nr.cpy_mv(s, d))

    # ---- expr pipeline driver ----
    def expr(self, *statements) -> "DataTree":
        """Apply a sequence of expr statements to this DataTree.

        Each statement is lowered to an invertible DataTree operation.
        Aggregates should be computed *before* calling `expr` — see
        the snapshot/aggregate boundary docs.

        Usage:
            dt.expr(
                assign(b.normalized_age, (b.age - mu) / std),
                keep(b.normalized_age < 50),
            )
        """
        try:
            from .expr.lower import run_expr  # type: ignore[import-not-found]
        except ImportError:
            from expr.lower import run_expr  # type: ignore[no-redef]
        return run_expr(self, *statements)
    
    def seal(self):
        """
        Throw away the history and return a "sealed" DataTree that can't be inverted.
         Useful for final output or when the history becomes too large to keep in memory.
        """
        return DataTree(self.twigs)


# ===========================================================================
# Adapters: drop these into laws.py in place of the reference factories.
# Every `forward` returns (new_state, undo_closure); `backward` just applies it.
# ===========================================================================
def _biop(make: Callable[[DataTree], DataTree]):
    def fwd(state: State):
        res = make(DataTree(state))
        return res.twigs, res.last_undo
    def bwd(state: State, undo: Undo):
        return undo(state)
    return fwd, bwd

def rowmap_set(key, value):
    return _biop(lambda t: t.map_set(key, value))

def filter_op(pred):
    return _biop(lambda t: t.filter(pred))

def insertion_op(new_twigs):
    return _biop(lambda t: t.insert(new_twigs))

def explode_op(key):
    return _biop(lambda t: t.explode(key))

def group_op(keyfn):
    return _biop(lambda t: t.group_by(keyfn))

def join_op(right, on, right_cols):
    return _biop(lambda t: t.join(right, on, right_cols))


if __name__ == "__main__":
    # Pipeline + full inversion demo (Claim B, constructively).
    tree = DataTree.from_records([
        {"name": "Alice", "age": 35,
         "edu": [{"inst": "A", "deg": "BSc"}, {"inst": "B", "deg": "MSc"}]},
        {"name": "Bob",   "age": 20, "edu": []},
        {"name": "Eve",   "age": 35, "edu": [{"inst": "C", "deg": "PhD"}]},
    ])

    # dotted-path projection -> columnar read
    print(tree.select(who="name", degrees="edu.deg")
              .col(who="who", degrees="degrees"))
    # {'who': ['Alice', 'Bob', 'Eve'], 'degrees': [['BSc','MSc'], None, ['PhD']]}

    # group by a path indexer
    for r, m in tree.group_by("age"):
        print(m["index"], r.data["group"],
          [member["data"]["name"] for member in r.data["members"]])
# 0 35 ['Alice', 'Eve']
# 1 20 ['Bob']

    # slicing sugar is an invertible filter
    assert tree[0:2].invert().twigs == tree[0:2].invert().twigs
    assert tree.head(2).invert().twigs == tree.twigs

    # path mutation, fully invertible (creates nested branch, then unwinds it)
    moved = tree.move("age", "profile.years")
    assert moved.invert().twigs == tree.twigs

    # record-level sugar
    r = Record({"a": {"b": {"c": 1}}})
    assert r["a.b.c"] == 1
    r["a.b.c"] = 2
    assert r["a.b.c"] == 2 and "a.b.c" in r

    # ── new syntactic sugar ───────────────────────────────────────────

    # tail / first / last
    assert len(tree.tail(2)) == 2
    assert tree.first() == {"name": "Alice", "age": 35,
                            "edu": [{"inst": "A", "deg": "BSc"},
                                    {"inst": "B", "deg": "MSc"}]}
    assert tree.last() == {"name": "Eve", "age": 35,
                           "edu": [{"inst": "C", "deg": "PhD"}]}

    # where (alias for filter)
    adults = tree.where(lambda r, m: r.data.get("age", 0) >= 35)
    assert len(adults) == 2
    assert adults.invert().twigs == tree.twigs

    # pluck
    assert tree.pluck("name") == ["Alice", "Bob", "Eve"]
    assert tree.pluck("edu.deg") == [["BSc", "MSc"], None, ["PhD"]]

    # drop (invertible)
    no_age = tree.drop("age")
    assert "age" not in no_age.first()
    assert no_age.invert().twigs == tree.twigs

    # rename via move chain (invertible)
    renamed = tree.rename(**{"age": "years_old"})
    assert "years_old" in renamed.first()
    assert "age" not in renamed.first()
    assert renamed.invert().twigs == tree.twigs

    # sort_by (invertible)
    by_name = tree.sort_by("name")
    assert [r.data["name"] for r, _ in by_name] == ["Alice", "Bob", "Eve"]
    rev = tree.sort_by("name", reverse=True)
    assert [r.data["name"] for r, _ in rev] == ["Eve", "Bob", "Alice"]

    # __add__ (insertion, invertible)
    extra = DataTree.from_records([{"name": "Dan", "age": 28, "edu": []}])
    combined = tree + extra
    assert len(combined) == 4
    assert combined.invert().twigs == tree.twigs

    # __or__ (pipe)
    def uppercase_names(dt: DataTree) -> DataTree:
        return dt.map_set("name", "ALICE")  # demo only — maps all rows
    piped = tree | uppercase_names
    assert piped.first()["name"] == "ALICE"
    assert piped.invert().twigs == tree.twigs

    # __bool__
    assert tree
    empty = tree.where(lambda r, m: False)
    assert not empty

    # __len__
    assert len(tree) == 3

    print("✅ All sugar tests passed.")