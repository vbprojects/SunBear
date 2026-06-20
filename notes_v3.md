# SunBearv3 — Invertible, Row-Based DataTree

## Architecture Overview

SunBearv3 is a **row-based** data processing engine built on an immutable,
thread-safe **DataTree** with **constructive invertibility** (L1/L2). Every
operation records a backward closure (complement) that can restore the
previous state — `invert_all()` unwinds the entire pipeline.

### Package Layout

```
src/sunbear/
├── __init__.py       # Package exports
├── DataTree.py       # Core: immutable row-based table with invertible ops
├── Record.py         # Row payload: path-based get/set/mv/add with indexer sugar
├── Schema.py         # Type-level schema trees (inference, reconciliation, diff)
├── ops.py            # sbo: value-tier expr ops (flatten, filter, map, reduce, chain, length)
└── expr/
    ├── __init__.py   # Expr builder public API
    ├── ast.py        # Expr base class, AST nodes, statements, Placeholder
    ├── namespace.py  # LazyNamespace (b), PathBuilder, Sym/Symbols, as_indexer
    ├── eval.py       # per-Record evaluator (OPS table, FUNCS registry)
    └── lower.py      # Statement lowering drivers (the only module touching DataTree)
```

## Core Concepts

### 1. DataTree — Immutable, Re-iterable Row Table

A `DataTree` is a sequence of **twigs**: `(Record, metadata)` pairs. Every
transform appends a backward closure to `_history`; `invert()` pops one,
`invert_all()` unwinds the full pipeline.

```python
dt = DataTree.from_records([{"a": 1}, {"a": 2}, {"a": 3}])
dt2 = dt.map_set("a", 99)
dt3 = dt2.filter(lambda r, m: r.data["a"] > 1)
original = dt3.invert_all()   # → dt.twigs == original.twigs
```

**Available ops (all invertible):**

| Op | Cardinality | Complement |
|---|---|---|
| `map_set(key, value)` | 1→1 | old value per row |
| `filter(pred)` | 1→{0,1} | dropped rows + indices |
| `insert(new_rows)` | n→n+m | provenance marker → filter |
| `explode(key)` | 1→n | group + reassemble |
| `join(right, on, cols)` | n→m | unmatched-left rows |
| `select(**aliases)` | 1→1 | original full records |
| `drop(*indexers)` | 1→1 | branch snapshot |
| `move(src, dst)` | 1→1 | branch snapshot |
| `copy(src, dst)` | 1→1 | branch snapshot |
| `sort_by(indexer)` | 1→1 | sort by original index |
| `group_by(key)` | n→g | ungroup + sort by index |
| `assign_at(path, fn)` | 1→1 | branch snapshot |
| `apply(fn)` | 1→1 | full-record snapshot |
| `take(start, stop)` | 1→{0,1} | dropped rows + indices |
| `head(n)` / `tail(n)` | 1→n | dropped rows + indices |

**Read-only collectors:**

- `col(**aliases)` → dict of lists
- `pluck(indexer)` → flat list
- `collect()` → list of dicts
- `inspect(indexer)` → Schema tree
- `schema` → inferred Schema
- `first()` / `last()` → single dict

### 2. Record — Row Payload

A `Record` wraps a dict with path-based access:

```python
r = Record({"a": {"b": {"c": 1}}})
r.get("a.b")          # → {"b": {"c": 1}}
r.get_leaves("a.b.c") # → 1
r.set("x.y", 42)      # creates nested path
r.mv("a.b", "p.q")    # moves to new path
r.cpy_mv("a.b", "r")  # copies
r["a.b.c"]            # → 1 (__getitem__ sugar)
```

**Indexer types:** string `"a.b"`, dotted str `"a.b.c"`, tuple `("a.b", "c")`,
list `["a", "b"]`, resolved dict `{"a": {"b": {}}}`.

### 3. Schema — Type-Level Schema Trees

The Schema module infers and reconciles type-level schemas from records:

```python
SchemaType hierarchy: Primitive, NullType, UnionType, ListType, CustomType
Node hierarchy: Leaf(type), Branch(fields)

Key semantics:
- Leaves are TYPE-INVARIANT: Leaf(int) == Leaf(str) == True
- Schemas are NULL-INVARIANT: missing fields ≡ None
- Schemas are NOT name-invariant: different field names ≠
- Non-transitive: A==B and B==C does NOT imply A==C
```

### 4. Expr Builder — Declarative Expression Pipeline

The `expr` package provides a **syntactic sugar layer** that lowers to
existing invertible DataTree ops. Every statement compiles to a `DataTree`
call whose complement already satisfies L1/L2.

#### Symbols and Namespace

```python
from sunbear.expr import Sym, Symbols, b

# Explicit symbols
age = Sym("record.age")
age, height = Symbols("record.age", "record.height")

# Lazy attribute-access PathBuilder
b.record.age           # → PathBuilder("record.age")
b.profile.bio.height   # → PathBuilder("profile.bio.height")
b["x y"]              # Bracket fallback for non-identifier fields
```

Both `Col`/`Sym` and `PathBuilder` are accepted by `pluck`, `col`, `select`,
`group_by`, `sort_by`, and `inspect` through `as_indexer` normalization.

#### Statements

| Statement | Constructor | Effect |
|---|---|---|
| `Assign` | `assign(target, value)` | Set a field per row |
| `Keep` | `keep(pred)` | Row-level filter |
| `MapAssign` | `b.target(fn)` or `map_assign(t, s, fn)` | Map fn over source to target |
| `Fork` | `fork(cond, then, else)` | Conditional branch (fast path) |
| `Case` | `case((c1,b1), ..., default=...)` | Multi-way branch (fast path) |

#### Value-Tier Ops (sbo)

```python
import sunbear.ops as sbo

sbo.flatten(value, level=-1)      # Recursive list flattening
sbo.filter(value, pred)           # Within-field filter
sbo.map(value, fn)                # Within-field map
sbo.reduce(value, fn, init=...)   # Within-field reduction
sbo.length(value)                 # Length of a list/string (aliases: size, count)
sbo.chain(seed, *steps)           # Build-time AST substitution pipeline
```

`chain` uses `_` (Placeholder) to thread the intermediate value:

```python
sbo.chain(
    sbo.flatten(b.tags, -1),
    sbo.filter(_, lambda x: isinstance(x, str)),
)
```

#### Expr Callable Syntax

`Expr.__call__` lets you transform a field with a lambda directly:

```python
from datetime import datetime
dt.expr(b.createdAt(lambda t: datetime.fromisoformat(t)))
# Equivalent to: assign(b.createdAt, sbo.map(b.createdAt, fn))
```

Write to a new field with `map_assign`:

```python
dt.expr(map_assign(b.createdAt_dt, b.createdAt, lambda t: datetime.fromisoformat(t)))
```

#### Examples

**Normalization with pre-computed aggregates:**

```python
mu = np.mean(dt.pluck(b.age))
std = np.std(dt.pluck(b.age))

dt.expr(
    assign(b.s_age, (b.age - mu) / std),
    keep(b.s_age < 2.0),
)
```

**Tags flattening + filter via chain:**

```python
dt.expr(
    assign(b.flat_tags, sbo.chain(
        sbo.flatten(b.tags, -1),
        sbo.filter(_, lambda x: isinstance(x, str)),
    )),
    keep(sbo.length(b.flat_tags) > 0),
)
```

**Fork (fast path):**

```python
dt.expr(fork(
    b.age > 99,
    assign(b.tier, "old"),
    assign(b.tier, "young"),
))
```

**Case (fast path):**

```python
dt.expr(case(
    (b.age >= 100, assign(b.tier, "old")),
    (b.age >= 18,  assign(b.tier, "adult")),
    default=[assign(b.tier, "minor")],
))
```

#### Aggregate Boundary

Aggregates are **eager Python** evaluated **before** `expr` is called,
against the tree as it was pre-`expr`. They do **not** see columns
created by earlier statements in the same `expr`. Split into two
`expr` calls if you need aggregates over derived state.

#### Invertibility

Every lowering is invertible — call `invert_all()` to unwind:

```python
original = dt.expr(assign(b.x, b.a * 2), keep(b.x > 0)).invert_all()
assert original.twigs == dt.twigs
```

### 5. Inversion Machinery

```python
dt._step(new_twigs, backward_closure) → DataTree  # appends to history
dt.invert()                                        # pops last op
dt.invert_all()                                    # unwinds all
```

Each backward closure maps `post_state → pre_state`. The complement
stored is the minimal data needed: branch snapshots for `_branch_map`,
original indices for `filter`, provenance markers for `insert`, etc.

## API Reference Summary

### DataTree

| Method | Signature | Description |
|---|---|---|
| `from_records` | `(records) -> DataTree` | Create tree from list of dicts |
| `schema` | property | Inferred schema |
| `twigs` | property | Cloned twig list |
| `scan` | `() -> Iterator` | Fresh iterator |
| `invert` | `() -> DataTree` | Undo last op |
| `invert_all` | `() -> DataTree` | Unwind all ops |
| `map_set` | `(key, value) -> DataTree` | Set scalar field |
| `filter` | `(pred: (r, m) -> bool) -> DataTree` | Keep matching rows |
| `keep` | alias for `filter` | |
| `where` | alias for `filter` | |
| `insert` | `(new_rows) -> DataTree` | Concatenate |
| `explode` | `(key) -> DataTree` | Unnest list field |
| `join` | `(right, on, cols) -> DataTree` | Keyed join |
| `select` | `(**aliases) -> DataTree` | Project columns |
| `drop` | `(*indexers) -> DataTree` | Remove fields |
| `move` | `(src, dst) -> DataTree` | Rename field path |
| `copy` | `(src, dst) -> DataTree` | Copy field path |
| `sort_by` | `(indexer, reverse) -> DataTree` | Sort rows |
| `group_by` | `(key) -> DataTree` | Group rows |
| `assign_at` | `(path, fn: r -> v) -> DataTree` | Per-row computed set |
| `apply` | `(fn: r -> Record) -> DataTree` | Whole-record map |
| `pluck` | `(indexer) -> list` | Column extraction |
| `col` | `(**aliases) -> dict` | Multi-column extraction |
| `collect` | `() -> list[dict]` | All records as dicts |
| `inspect` | `(indexer) -> Schema` | Schema inference |
| `expr` | `(*statements) -> DataTree` | Expression pipeline |
| `head` / `tail` | `(n) -> DataTree` | Positional sugar |
| `__add__` | `(other) -> DataTree` | Concatenation sugar |
| `__or__` | `(fn) -> DataTree` | Pipe operator |

### Record

| Method | Description |
|---|---|
| `get` | Walk path, return structured result |
| `get_leaves` | Walk path, return leaf values (bare or flat list) |
| `set` | Walk/create path, set leaf value |
| `add` | Set only if absent |
| `mv` | Move value between paths |
| `cpy_mv` | Copy value between paths |
| `__getitem__` | `r["a.b"]` sugar |
| `__setitem__` | `r["a.b"] = v` sugar |

### Schema

| Type | Description |
|---|---|
| `SchemaType` | Abstract base (`Primitive`, `NullType`, `UnionType`, `ListType`, `CustomType`) |
| `Leaf` | Terminal node (type-invariant) |
| `Branch` | Named container (null-invariant, subset-equivalent) |
| `Schema` | High-level wrapper with `from_records`, `filter`, `show`, `type_stats` |

### Expr

| Module | Key Exports |
|---|---|
| `expr.ast` | `Expr`, `Lit`, `Col`, `BinOp`, `UnOp`, `Call`, `Placeholder`, `Statement`, `Assign`, `Keep`, `Fork`, `Case`, `MapAssign`, `assign`, `map_assign`, `keep`, `fork`, `case`, `_`, `_wrap`, `substitute` |
| `expr.namespace` | `Sym`, `Symbols`, `PathBuilder`, `LazyNamespace`, `b`, `as_indexer` |
| `expr.eval` | `eval_value`, `eval_predicate`, `OPS`, `FUNCS` |
| `ops` | `flatten`, `filter`, `map`, `reduce`, `chain`, `length`, `size`, `count` |

## Test Suite

Run all expr tests:

```bash
python -m unittest tests.test_expr
```

Run specific class:

```bash
python -m unittest tests.test_expr.TestSpecForkExample
```

Current test count: **39 tests** covering spec examples, M0 evaluator,
namespace helpers, chain validation, invertibility for every lowering,
edge cases (missing nested branch, overwrite), random fuzz (20 trials),
`sbo.length`, `inspect` with Symbols, and `Expr.__call__`.