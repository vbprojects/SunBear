# Program — Deferred Expr Pipeline with Row-Based Caching

`Program` stores a sequence of **expr statements** (tuples from `assign()`,
`keep()`, etc.) and replays them on a DataTree when called. Caching is
**row-based**: each input record is hashed individually; cache hits return
stored output rows, cache misses run the full pipeline on a single-row
DataTree.

**Key design decisions:**

- **Expr-only** — Programs only accept `expr` statements (not arbitrary
  DataTree methods). For complex pipelines, compose with `dt.expr()` directly.
- **Row-based caching** — each row is hashed (SHA-256 of sorted JSON).
  Rows filtered out by `keep` are cached as `null` and skipped on replay.
- **Persistent cache** — `FileCache` stores JSON files in `.sunbear_cache/`.
  A custom cache name (or auto-hash from statements) keys the file.

---

## Usage

### Basic Pipeline

```python
from sunbear import Program, DataTree
from sunbear.expr import b, assign, keep

dt = DataTree.from_records([
    {"name": "Alice", "age": 30, "score": 85},
    {"name": "Bob",   "age": 17, "score": 42},
    {"name": "Carol", "age": 25, "score": 91},
])

prog = Program(name="adults").expr(
    assign(b.tier, "standard"),
    keep(b.age >= 18),
)

result = prog(dt)   # cache miss — executes pipeline
result = prog(dt)   # cache hit — skips computation
```

### Pipe Syntax

```python
result = dt | prog
```

### Loading Cached Results

```python
dt_from_cache = prog.to_DataTree()
```

---

## Program Construction

```python
# Auto-hashed cache name (derived from statements)
prog = Program().expr(assign(b.x, 1))

# Explicit name (human-readable cache file)
prog = Program(name="my_pipeline").expr(assign(b.x, 1))

# Custom cache backend
from sunbear import FileCache
prog = Program(cache=FileCache("my_pipeline")).expr(assign(b.x, 1))
```

### `Program.__repr__()`

```python
>>> prog = Program(name="test").expr(assign(b.status, "ok"))
>>> repr(prog)
"Program('test', 1 stmts)"

>>> Program().expr(assign(b.x, 1))
"Program('<auto>', 1 stmts)"
```

---

## Cache Architecture

### Row Hashing

Each input record's `data` dict is hashed with `_row_hash`:

```python
def _row_hash(data: dict) -> str:
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

### Program Key (Cache Namespace)

The program key determines the cache file name:

1. If `name` is provided, it's used directly.
2. Otherwise, statements are serialized to stable JSON and SHA-256 hashed.

```python
prog_a = Program().expr(assign(b.x, 1))
prog_b = Program().expr(assign(b.x, 1))
# Same statements → same auto-hash → same cache
```

---

## AbstractCache Backend

### `AbstractCache` (ABC)

| Method | Description |
|---|---|
| `get(row_key) -> dict | _FILTERED | None` | Return `dict` for hit, `_FILTERED` for filtered rows, `None` for miss |
| `set(row_key, output)` | Cache output dict (or `None` for filtered) |
| `to_DataTree()` | Reconstruct DataTree from all cached rows |

### `FileCache`

JSON-file backend at `.sunbear_cache/{name}.json`.

**File format:**
```json
{
  "<row_key>": {
    "data": {...} | null,
    "ts": <epoch_timestamp>
  },
  ...
}
```

- `data: null` means the row was filtered out.
- `to_DataTree()` loads all non-null cached entries.

```python
from sunbear import FileCache

cache = FileCache("adults")
cache.set("abc123", {"name": "Alice", "tier": "standard"})
data = cache.get("abc123")  # {"name": "Alice", "tier": "standard"}
```

---

## Execution Flow

When `prog(dt)` is called:

1. Resolve cache (lazily creates `FileCache` if none provided)
2. For each `(record, meta)` in the DataTree:
   - Hash `record.data` to get `row_key`
   - Check cache:
     - `_FILTERED` → skip row
     - `dict` → cache hit, append to output
     - `None` → cache miss:
       1. Wrap in single-row DataTree
       2. Run full expr pipeline
       3. If result empty → cache as `null` (filtered)
       4. Else → cache output dict, append to output
3. Return `DataTree.from_records(out_rows)` (re-traversable)

---

## `to_DataTree()`

Reconstruct a standalone DataTree from all cached (non-filtered) rows:

```python
prog = Program(name="adults").expr(assign(b.tier, "standard"), keep(b.age >= 18))
result = prog(dt)

# Later, load results without re-executing:
dt_cached = prog.to_DataTree()
```

Raises `RuntimeError` if no cache is configured.
