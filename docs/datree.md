# DataTree — Lazy Row-Based Table

`DataTree` is the core table abstraction in SunBear. It stores an iterable of
`(Record, meta)` tuples (called **Twigs**) and provides lazy transformations
(maps, filters, branches) that return new DataTree generators without
materializing intermediate results.

**Key design decisions:**

- **No invertibility** — no undo history, no provenance markers. Records are
  mutable and shared by reference.
- **Lazy by default** — `map`, `filter`, `branch_map`, `insert`, `take` all
  return generators. Only terminal operations (`collect`, `pluck`, `rows`,
  `group_by`, `join`, `sort_by`) drain the stream.
- **Plan layer** — inter-record ops (`group_by`, `join`, `reduce_by`) build a
  `Plan` index with automatic cardinality detection.

---

## Construction

### `DataTree.from_records(records)`
Construct from a list of plain dicts. **Eagerly materialized** (re-traversable).
Each row gets auto-index metadata `{"i": <index>}`.

```python
from sunbear import DataTree

dt = DataTree.from_records([
    {"name": "Alice", "age": 30},
    {"name": "Bob", "age": 25},
])
```

### `DataTree.from_iter(it)`
Stream from any iterable of dicts. **Single-pass** — the generator is consumed
on the first traversal; use `from_records` for re-traversable streams.

```python
def gen():
    yield {"x": 1}
    yield {"x": 2}

dt = DataTree.from_iter(gen())
```

---

## Lazy Primitives

All return a new `DataTree` backed by a generator. No work is done until
a terminal operation is called.

| Method | Description |
|---|---|
| `dt.map(fn)` | Whole-record map. `fn(record) -> record` |
| `dt.filter(pred)` | Record-level filter. `pred(record, meta) -> bool` |
| `dt.branch_map(roots, fn)` | Shallow-copy record then `fn(record)` in-place. `roots` declares which top-level keys are copied |
| `dt.insert(rows)` | Append rows from any iterable of `(Record, meta)` |
| `dt.take(start, stop)` | Slice by position (`itertools.islice`) |
| `dt.head(n=5)` | First n rows |
| `dt.tail(n=5)` | Last n rows (forces materialization) |

```python
dt2 = dt.map(lambda r: r.set("status", "active"))
dt3 = dt2.filter(lambda r, m: r.get("age") >= 18)
dt4 = dt3.branch_map(["name"], lambda r: r.set("name", r.get("name").upper()))
```

---

## Mutation Sugar (also lazy)

| Method | Description |
|---|---|
| `dt.set(indexer, value)` | Set path to constant value |
| `dt.add(indexer, value)` | Set only if missing (`None` treated as missing) |
| `dt.move(src, dst)` | Move value from src path to dst path |
| `dt.copy(src, dst)` | Copy value from src path to dst path (keeps src) |
| `dt.drop(*indexers)` | Remove fields by path |
| `dt.rename(**mapping)` | Rename fields: `dt.rename(old="new")` |
| `dt.assign_at(path, fn)` | Set `fn(record)` at path on every row |

---

## Terminal Extractors

These drain the DataTree and return concrete data structures.

| Method | Returns |
|---|---|
| `dt.collect()` | `list[dict]` — all rows as plain dicts |
| `dt.pluck(indexer)` | `list[Any]` — single column values |
| `dt.rows(**aliases)` | `list[dict]` — row-wise: `[{alias: value, ...}]` |
| `dt.col(**aliases)` | `dict` — columnar: `{alias: [values, ...]}` |
| `dt.iterrows(**aliases)` | `Iterator[dict]` — row-wise iterator |
| `dt.itercols(**aliases)` | `Iterator[dict]` — column-wise iterator |
| `dt.iterpluck(indexer)` | `Iterator[Any]` — single column iterator |
| `dt.itercollect()` | `Iterator[dict]` — each row as a plain dict |

```python
vals = dt.pluck("age")
for row in dt.iterrows(name="name", a="age"):
    print(row["name"], row["a"])
```

---

## Inter-Record Ops (Plan Layer)

### `dt.group_by(key, *reduce_fns)`
Group rows by `key` (indexer or callable). If reduce_fns given, each is called
as `fn([records])` per group; values stored under `"v"` or `"v_0", "v_1"...`

```python
grouped = dt.group_by("age", lambda members: len(members))
```

### `dt.join(right, on, how="inner")`
Join with a list of right-side dicts on field `on`. Builds an index over the
right side (assumed smaller). Supports `"inner"` and `"left"` joins.

```python
right = [{"name": "Alice", "score": 85}]
joined = dt.join(right, on="name", how="left")
```

### `dt.reduce(fn, init=SENTINEL)`
Terminal fold over rows. Without `init`, the first record's data is the seed.

### `dt.reduce_by(key, fn, init=SENTINEL)`
Group + reduce in a single pass. Returns DataTree of `(key, value)`.

### `dt.sort_by(indexer, reverse=False)`
Materialize + sort by the value at `indexer`.

---

## Plan Object

Build a `Plan` explicitly for introspection via `.explain()`:

```python
plan = dt.plan("age")
print(plan.explain())
# Plan(key=..., cardinality=1:1, side=left, keys=2, rows=2, avg_per_key=1.00)
```

Plan detects cardinality by sampling the first 64 rows:
- **1:1** — every key unique
- **1:N / N:1** — sided repetition
- **N:M** — both sides have repeated keys

---

## Schema Introspection

```python
schema = dt.schema   # materializes, infers, and reconciles all rows
schema.show()        # Unicode tree (terminal) or collapsible HTML (Jupyter)
```

---

## Expr Pipeline

```python
from sunbear.expr import b, assign, keep

dt2 = dt.expr(
    assign(b.status, "active"),
    keep(b.age >= 18),
)
```

---

## Operator Overloading

| Operation | Behavior |
|---|---|
| `dt + other` | Append rows: `dt.insert(other.scan())` |
| `dt \| fn` | Pipe: `fn(dt)`. Works with `Program` instances |

---

## Twig Protocol

Each row in a DataTree is a `Twig = Tuple[Record, dict]`:

```python
for record, meta in dt.scan():
    print(record.data, meta)
```
