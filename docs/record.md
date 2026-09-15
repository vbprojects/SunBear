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

## Structured paths and missing values (0.3)

Expression paths store typed Key, Index, and Traverse segments. Legacy dotted
strings still address nested fields, and dict/list/tuple indexers remain
accepted by Record.resolve(). Use bracket syntax for literal keys and method
name collisions:

```python
from sunbear import Record, MISSING
from sunbear.expr import b

r = Record({"literal.key": [{"price": None}, {"price": 7}]})
assert r.get(b["literal.key"][-1].price) == 7
assert r.get(b["literal.key"][0].price) is None
assert r.get(b["literal.key"][9], MISSING) is MISSING
```

Integer indices support Python negative indices. Out-of-range reads are
missing; writes raise IndexError and never extend arrays implicitly.
b.items[...].price explicitly traverses a list; b.items.price retains implicit
list traversal. Traversal preserves nulls and empty collections but omits
missing matches. Thus traversing an empty list returns [], and [{x: null}, {}]
produces [null]. Traversal results are not position-aligned with missing items.

Record.get(path) retains the legacy None default; pass MISSING explicitly to
distinguish absence. Expression evaluation retains MISSING automatically.
exists() tests presence (including null), is_null() tests explicit null,
is_not_null() tests present non-null values, and fill_missing(value) replaces
absence only. Use these instead of comparing with None when absence matters.
Boolean expression & and | short-circuit, allowing guarded missing access.

Move/copy preserve explicit null. add() fills only absence. default() retains
its legacy missing-or-null fallback; fill_missing() is the precise alternative.
Missing output object fields are omitted; missing array positions raise.

Record is mutable at the root. Declarative writes copy modified ancestor
containers and assigned values so deep updates do not mutate source/sibling
branches. Untouched containers remain shared; direct dict mutation bypasses
this guarantee. branch_map callbacks deeply copy declared roots, and must not
mutate undeclared roots. Whole-record map callbacks retain their explicit
mutable Record interface.
