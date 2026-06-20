# DataTree — Invertible Row-Based Data Engine

The `DataTree` is the core container in SunBear. It holds a collection of **twigs** (row+metadata pairs) and provides a rich set of **invertible** transformations — every operation can be undone, making the full pipeline **transitively reachable**.

## Core Architecture

```
DataTree
├── _twigs: List[Twig]       # materialized snapshot (Record, metadata)
├── _history: Tuple[Undo]    # backward closures (one per operation)
├── from_records(records)    # constructor from list of dicts
├── scan() / __iter__()      # fresh iterator each call (thread-safe)
├── invert()                 # pop one undo
└── invert_all()             # unwind entire pipeline
```

**Twig** = `Tuple[Record, dict]` — a row plus its metadata (index, provenance, etc.).

**State** = `List[Twig]` — the materialized snapshot.

**Undo** = `Callable[[State], State]` — a backward closure that maps post-state → pre-state.

### Immutability & Re-iteration

```python
dt = DataTree.from_records(records)
for r, m in dt: ...   # fresh iterator each time
for r, m in dt: ...   # independent — no exhaustion
```

Every `scan()` call returns a fresh, independent iterator. The backend is a materialized snapshot `_twigs` that is **defensive-copied** on every access (`_clone`), so iteration is thread-safe.

## Inversion Machinery

Every transform appends a **backward closure** to `_history`:

```python
def _step(self, new_twigs, backward):
    return DataTree(new_twigs, self._history + (backward,))
```

- `invert()` — pops the last undo: `*rest, back = self._history; return DataTree(back(self.twigs), rest)`
- `invert_all()` — unwinds the full pipeline back to source
- `last_undo` — property exposing the most recent backward closure

### The `_biop` Adapter

```python
def _biop(make: Callable[[DataTree], DataTree]):
    def fwd(state: State):
        res = make(DataTree(state))
        return res.twigs, res.last_undo
    def bwd(state: State, undo: Undo):
        return undo(state)
    return fwd, bwd
```

This wraps any `DataTree` method into a (forward, backward) pair for use in the laws module.

## Operator Classes

Each operator stores a **complement** — the minimal information needed to reconstruct the pre-state.

### 1. Row Map (`map_set`) — 1→1, self-dual

```python
dt.map_set("name", "ALICE")
```

**Complement**: old value per row (stored in `_undo` metadata).

```python
def back(post):
    for r, m in post:
        old = m[_UNDO]          # the original value
        d = dict(r.data)
        d.pop(key, None) if old is _MISSING else d.__setitem__(key, old)
```

### 2. Filter — 1→{0,1}

```python
dt.filter(lambda r, m: r.data.get("age", 0) >= 35)
```

**Complement**: dropped rows + their original indices.

```python
def back(post):
    out = list(post)
    for i, twig in dropped:     # ascending i → exact re-insertion
        out.insert(i, twig)
```

### 3. Insertion — n→n+m

```python
dt.insert(new_twigs)
```

**Complement**: provenance marker (`_INS`). Inverse is a **filter** that removes marked rows.

```python
def back(post):
    return [(r, m) for r, m in post if not m.get(_INS)]
```

### 4. Explode — 1→n

```python
dt.explode("edu")
```

**Complement**: parent skeleton + position metadata. Inverse = **group + reassemble** (n→1).

### 5. Join — n→m

```python
dt.join(right_list, on="city", right_cols=["population"])
```

**Complement**: unmatched-left rows. Inverse = **collapse fan-out** (m→n).

### 6. Group By — n→m

```python
dt.group_by("age")
```

Groups rows by a key (indexer or callable), producing `{"group": key, "members": [...]}`. Inverse = **flatten** members back.

### 7. Select — n→n (projection)

```python
dt.select(who="name", degrees="edu.deg")
```

**Complement**: original row data. Inverse = **restore** from deepcopy.

### 8. Path Mutations (`_branch_map`)

```python
dt.set("profile.age", 30)
dt.add("tags", ["new"])
dt.move("age", "profile.years")
dt.copy("age", "profile.age_copy")
dt.drop("age")
dt.rename(**{"old.path": "new.path"})
```

All use `_branch_map` — snapshots the **touched top-level branches** before mutation, restores them on invert.

### 9. Positional Sugar

```python
dt.take(0, 5)       # invertible slice
dt.head(5)          # first n rows
dt.tail(5)          # last n rows
dt[0:2]             # __getitem__ slice → take
```

All are **invertible filters** — complement = dropped rows.

### 10. Sorting

```python
dt.sort_by("name")
dt.sort_by("name", reverse=True)
```

**Complement**: original index order. Inverse = **re-sort by index**.

### 11. Columnar Reads

```python
dt.col(who="name")           # → {"who": ["Alice", "Bob", ...]}
dt.pluck("name")              # → ["Alice", "Bob", ...]
dt.inspect("age")             # → Schema of values at path
```

These are **read-only** — no history appended.

### 12. Pipe / Concatenation

```python
dt | uppercase_names          # __or__ → pipe
dt + other_tree               # __add__ → insert
```

## L1/L2 Invertability

The framework satisfies **L1** (each operation is individually invertible) and **L2** (the composition of operations is invertible). Every `_step` call appends a closure; `invert_all` unwinds them all.

```python
# Pipeline
t = (dt
    .select(who="name")
    .where(lambda r, m: r.data["age"] > 25)
    .map_set("name", "UPPERCASE")
)

# Full inversion
assert t.invert_all().twigs == dt.twigs
```

## Key Design Notes

- **`_MISSING`** is the sentinel for absent values — survives deepcopy and pickle
- **`_freeze`** makes `get_leaves` output hashable for group keys
- **`_clone`** is a deep copy of state — ensures immutability
- **`_deep_merge`** is recursive dict merge for indexer resolution
- Metadata always carries `"index"` — the original row position for stable inversion