# Record — Row Payload with Path-Based Indexer Sugar

The `Record` class is the **row payload** in SunBear. It wraps a plain `dict` and provides a rich API for **path-based** get/set/mv/add operations using **indexer sugar**.

## Core Structure

```python
Record(data: dict)
```

- `data` — the underlying dict (mutable)
- `__eq__` — by `data` equality
- `__hash__ = None` — records are **unhashable** (mutable)

## Indexer Resolution

Indexers are **resolved** into nested dict paths:

```python
Record._resolve_indexer(indexer) → dict
```

| Input | Resolved |
|-------|----------|
| `"a.b.c"` (str) | `{"a": {"b": {"c": {}}}}` |
| `"a"` (simple) | `{"a": {}}` |
| `("a.b", "c.d")` (tuple) | merged: `{"a": {"b": {}}, "c": {"d": {}}}` |
| `["a", "b"]` (list) | merged: `{"a": {}, "b": {}}` |
| `{"a": {"b": {}}}` (dict) | returned as-is (already resolved) |

### Merging

Multiple indexers in a list/tuple are **deep-merged**:

```python
_deep_merge(dst, src) → dict
```

Recursively merges `src` into `dst` — dict values at the same key are merged recursively.

## Walkers

### `_walk_get(node, path)` — Recursive Get

Traverses a nested structure following the resolved path:

- **dict** → recurse into each key's sub-path
- **list** → collect from each item, merge by key
- **None** → return `None`
- **non-dict/non-list** → return `None`

Returns a **merged dict** — values from list items are collected into lists.

### `_walk_set(node, path, value)` — Recursive Set

```python
for k, sub in path.items():
    if isinstance(sub, dict) and sub:
        node[k] = {} if not isinstance(node.get(k), dict)
        _walk_set(node[k], sub, value)
    else:
        node[k] = value
```

Creates intermediate dicts as needed.

### `_walk_delete(node, path)` — Recursive Delete

```python
keys = list(path.keys())
cur = node
for k in keys[:-1]:
    if not isinstance(cur.get(k), dict): return
    cur = cur[k]
cur.pop(keys[-1], None)
```

Walks to the parent, then pops the last key.

## Public API

### `get(indexer)`

```python
record.get("a.b.c") → value
```

Returns the **nested dict** at the path (preserves structure).

### `get_leaves(indexer)`

```python
record.get_leaves("a.b.c") → leaf_value
```

**Flattens** to leaf values:
- Single-key dict → unwrap
- Multi-key dict → list of values
- List → list of leaf values

### `set(indexer, value)`

```python
record.set("a.b.c", 42)
```

Sets a value at the path, creating intermediate dicts.

### `add(indexer, value)`

```python
record.add("a.b.c", 42)
```

**Conditional set** — only sets if the path is currently `None`.

### `mv(src, dst)`

```python
record.mv("a.b", "x.y")  # move a.b → x.y
```

1. `get_leaves(src)` — extract value
2. `_walk_delete(src)` — remove source
3. `set(dst, value)` — place at destination

### `cpy_mv(src, dst)`

```python
record.cpy_mv("a.b", "x.y")  # copy a.b → x.y (no delete)
```

Copy without delete — **preserves** the source.

## Sugar Operators

### `__getitem__` — `record["a.b.c"]`

```python
record["a.b.c"]  # → get_leaves("a.b.c")
```

### `__setitem__` — `record["a.b.c"] = v`

```python
record["a.b.c"] = 42  # → set("a.b.c", 42)
```

### `__contains__` — `"a.b.c" in record`

```python
"a.b" in record  # → get("a.b") is not None
```

## Sentinel: `_MISSING` / `_Missing`

```python
_MISSING = _Missing()  # singleton
```

- Survives `deepcopy` and `pickle`
- Used as the **absent-value sentinel** in DataTree complements
- `__deepcopy__` returns `self` — preserves identity
- `__reduce__` returns `(_Missing, ())` — pickles as singleton

## Utility Functions

### `_freeze(v)`

```python
_freeze(v) → hashable
```

- `list` → `tuple(_freeze(x) for x in v)`
- `dict` → `tuple(sorted((k, _freeze(x)) for k, x in v.items()))`
- Otherwise → `v` (as-is)

Makes `get_leaves` output **hashable** for group keys.

### `_deep_merge(dst, src)`

Recursive merge — dict values at the same key are merged recursively.

### `construct_schema(record)`

```python
construct_schema({"a": 1, "b": {"c": "hi"}})
# → {"a": "int", "b": {"c": "str"}}
```

Infer a **type-level schema** from a record dict — walks the tree and maps values to their `type.__name__`.