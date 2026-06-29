# Record — Row Payload with Recursive Walk

`Record` is the row payload in SunBear. It wraps a `data` dict (the record's
fields) and a `meta` dict (used for plan annotations, lazy skip-flags, etc.).

**Key design decisions:**

- **Mutable, shared by reference** — no defensive copies. This is by design
  for performance: index entries reference the same Record objects.
- **Single recursive `_walk`** — one function handles get, set, and delete
  guided by a nested-dict path.
- **Rich indexer resolution** — dotted strings, tuples, lists, dicts, and
  expr leaves (Path/Col) all resolve to a uniform nested-dict path.

---

## Construction

```python
from sunbear import Record

r = Record({"name": "Alice", "profile": {"age": 30, "city": "NYC"}})
r = Record(data={"a": 1}, meta={"source": "api"})  # with metadata
```

---

## Indexer Resolution

The indexer is any value that `Record.resolve()` can normalize to a nested-dict
path. Supported forms:

| Form | Example | Resolves to |
|---|---|---|
| **Dotted string** | `"profile.age"` | `{"profile": {"age": {}}}` |
| **Plain string** | `"name"` | `{"name": {}}` |
| **Dict** | `{"profile": {"age": {}}}` | Passed through |
| **Tuple/list** | `("name", "profile.age")` | Merged via `_deep_merge` |
| **Expr leaf (Path/Col)** | `b.profile.age` | Extracts `.indexer` |

```python
r = Record({"a": {"b": {"c": 1}}})

# All equivalent:
r.get("a.b.c")
r.get({"a": {"b": {"c": {}}}})
r.get(["a.b", "c"])   # merged from two paths
```

---

## The `_walk` Method

`Record._walk(node, path, action, value=None)` is the single recursive helper:

- **`"get"`** — returns the leaf value, or `None` if missing or the path
  reaches a non-dict node
- **`"set"`** — creates intermediate dicts as needed, assigns value at leaf
- **`"delete"`** — pops the leaf, no-op if missing

```python
# _walk on a raw dict:
path = Record.resolve("a.b.c")
result = Record._walk({"a": {"b": {"c": 42}}}, path, "get")
# result == 42
```

---

## Public API

### Getters / Setters

| Method | Description |
|---|---|
| `r.get(indexer)` | Get value at path |
| `r.set(indexer, value)` | Set value at path. Returns `self` |
| `r.delete(indexer)` | Delete field at path. Returns `self` |
| `r.add(indexer, value)` | Set only if missing (None treated as missing). Returns `self` |
| `r.mv(src, dst)` | Move value from src to dst. Returns `self` |
| `r.cpy(src, dst)` | Copy value from src to dst (keeps src). Returns `self` |

### Dict-like Sugar

| Method | Description |
|---|---|
| `r[indexer]` | `r.get(indexer)` |
| `r[indexer] = value` | `r.set(indexer, value)` |
| `indexer in r` | `r.get(indexer) is not None` |

---

## Metadata

The `meta` dict stores per-row annotations:

- **`"i"`** — auto-assigned index from `from_records` / `from_iter`
- **`"_skips"`** — lazy filter skip masks (set by `sbo.filter`)

```python
r = Record({"a": 1}, {"source": "api"})
print(r.meta)  # {"source": "api"}
```

---

## Freeze Helper

`Record._freeze(v)` / `sunbear._freeze(v)` makes values hashable for
group_by/join keys:

- Lists → tuples
- Dicts → sorted tuples of `(k, frozen_v)`
- Everything else passes through unchanged

---

## Path Resolver Internals

### `_mkpath(s: str) -> dict`
Converts a dotted string to a nested-dict path:
```
"a.b.c" → {"a": {"b": {"c": {}}}}
""      → {}
```

### `_deep_merge(dst, src) -> dict`
Recursively merges src into dst in-place. Used by tuple/list indexers to
combine multiple paths.
