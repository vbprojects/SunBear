# SunBear

**A lazy, schema-aware JSON data engine — like pandas mixed with jq, built for tree-structured data.**

SunBear lets you query, filter, aggregate, and transform collections of JSON records using a concise Pythonic API. It infers schemas from your data, indexes records by schema variant, and chains lazy operations into a DAG that only materialises when you call `.collect()`.

---

## Quick Start

```python
from src.DataTree import DataTree

records = [
    {"name": "Alice", "age": 30, "city": "New York"},
    {"name": "Bob",   "age": 25, "city": "Los Angeles"},
    {"name": "Charlie","age": 35, "city": "Chicago"},
]
dt = DataTree(records)

# Project a column — lazy, returns a DataBranch
dt[:, "name"].collect()           # ["Alice", "Bob", "Charlie"]

# Multiple columns
dt[:, ["name", "age"]].collect()  # [["Alice", 30], ["Bob", 25], ["Charlie", 35]]

# Filter with a predicate
dt[:, "age"].shallow(lambda x: x > 28).collect()  # [30, 35]

# Group by a field
dt[:, "city"].group_by().collect()
```

---

## Installation

No pip package yet — clone the repo and import from `src/`:

```bash
git clone https://github.com/your-org/sunbear.git
cd sunbear
```

Requires **Python 3.10+**. No external dependencies.

---

## Core Concepts

### DataTree

The base container. Holds a list of dict records, infers their schemas, and maps each record to its schema variant.

```python
dt = DataTree(records)                  # infers schemas immediately
dt = DataTree(records, defer_evaluation=True)  # lazy — schemas built on first access
```

### DataBranch

A lazy view over a `DataTree` (or another `DataBranch`). Chaining operations creates a DAG of transformations:

```python
branch = dt[:, "age"]           # DataBranch with a projection column
branch = branch.shallow(...)    # DataBranch with a filter/map operation
result = branch.collect()       # materialise → plain list or DataTree
```

Every operation returns a new `DataBranch` — nothing mutates in place.

### Schemas

SunBear infers a schema tree from each record. Schema comparison uses **subset semantics**:

- `(a=(b=int, c=str)) == (a=(b=str, c=int))` → `True` (type-invariant)
- `(a=(b=int)) == (a=(b=int, c=None))` → `True` (null-invariant)
- `(a=(b=int, c=str)) == (a=(c=str, b=int, d=int))` → `False` (name-sensitive)

Schemas can be **non-transitive**: $A = B$ and $B = C \not\Rightarrow A = C$. When this happens, a warning is raised and you can reconcile to find the minimum union tree.

#### Why Transitive Schema Matters

SunBear is designed for messy, semi-structured data. In real datasets, optional fields often appear as `None` in some records and as nested objects in others. That can create **non-transitive schema equality**: two schemas may each be compatible with an intermediate schema, but not with each other.

Example:

```python
from src.DataTree import DataTree

dt = DataTree([
    {
        "event_id": "e1",
        "user_id": 101,
        "label": {
            "clicked": 1,
            "dwell_time_sec": 42.7,
        },
    },
    {
        "event_id": "e2",
        "user_id": 102,
        "label": None,
    },
    {
        "event_id": "e3",
        "user_id": 103,
        "label": {
            "purchased": 1,
            "revenue_usd": 89.99,
            "attribution": {
                "channel": "email",
                "campaign": "spring_launch",
            }
        },
    },
])
```

Essentially, we have cannot infer a single structure for the data and say record 2 is missing some fields. In this case, it looks like we have multiple different datasets, and we have to figure out what we are actually looking at to gain domain knowledge. 

a dataset with a single schema can be conerted to tidy data, which is ideal for data analysis. Multiple schemas can be reconciled, just taking the union of all fields and treating missing keys as `None`. The point is that we want to eventually turn tree based data into tabular data, and we need to be able to reason about the structure of the data to do that.
---

## Indexing

SunBear uses 2D indexing: `dt[row, column]`

| Row selector | Behaviour |
|--------------|-----------|
| `:` | All records |
| `int` | Single record by index |
| `slice` | Range of records |
| `list[int]` | Specific indices |
| `dict` | Schema-based pruning — only loads matching keys |

| Column selector | Behaviour |
|-----------------|-----------|
| `str` | Depth traversal via dot-notation: `"post.record.text"` |
| `tuple` | Explicit depth path: `("education", "degree")` |
| `list[str]` | Breadth projection: `["name", "age", "occupation"]` |
| `:` | No projection — full records |

### Sub-tree traversal

When a depth path hits a list of dicts mid-traversal, remaining segments are mapped across each element:

```python
# facets is a list of dicts; .features is resolved inside each one
dt[:, "post.record.facets.features"].collect()
# → [[[{...}, ...]], [[{...}]], ...]
```

---

## Operations

### Filtering and transformation

| Method | Behaviour |
|--------|-----------|
| `.shallow(func)` | Apply `func` to projected value. Returns `bool` → filter; returns value → mutate. |
| `.deep(func)` | Recursively walk every leaf in the record. |
| `.isna()` | Filter to records where projected value is `None`. |
| `.not_(func)` | Negate a predicate. |
| `.assign(val)` | Set projected path(s) to `val` for every record. |

```python
dt[:, "age"].shallow(lambda x: x > 30)       # filter
dt[:, "age"].shallow(lambda x: x * 2)         # mutate
dt.isna().length()                            # count nulls
dt[:, "age"].assign(0)                        # set all ages to 0
```

### Aggregation and partitioning

| Method | Behaviour |
|--------|-----------|
| `.group_by(target_node="members")` | Bins records by projected column. Detects list-valued paths and applies inner grouping. |
| `.aggregate()` | Collects non-`None` projected values into a single list under the path key. |
| `.add_path(dest, source)` | Injects source values at a destination path. `".."` wraps the record in a new root dict. |

```python
# group by occupation
dt[:, "occupation"].group_by().collect()
# → [{"occupation": "Engineer", "members": [...]}, ...]

# chained group-by (outer: city, inner: occupation)
dt[:, "city"].group_by()[:, "members.occupation"].group_by().collect()

# wrap filtered records in a dynamic key
db = dt[:, "occupation"].filter(lambda x: x == "Engineer")
db.add_path("..", db[:, "occupation"]).collect()
# → [{"Engineer": {...}}, ...]
```

### Path extraction

```python
dt.path(["post.record.text", "post.record.createdAt"]).collect()
# → [{"text": "...", "createdAt": "..."}, ...]
```

Always returns a `DataTree`, so you can chain further operations.

### Custom extensions

Register new methods on both `DataTree` and `DataBranch`:

```python
@DataTree.register_method
@DataBranch.register_method
def head(db, n=5):
    import itertools
    return DataBranch(db, operation=lambda r: list(itertools.islice(r, n)))

dt.head(10).collect()  # first 10 records
```

---

## Collect output types

| Condition | Output |
|-----------|--------|
| `return_tree = True` | `DataTree` |
| `projection_col` is set | `list` (of scalars or lists) |
| Neither | `list` if source is a generator, else raw records |

---

## Design principles

- **Lazy by default.** Operations build a DAG. Nothing evaluates until `.collect()`.
- **Tree-native.** Schemas are trees, paths are trees, grouping preserves tree structure.
- **Composable.** Every operation returns a `DataBranch` or `DataTree` — chain freely.
- **Schema-aware.** Records are indexed by schema variant, enabling fast filtering and structural queries.

---

## Project structure

```
src/
  DataTree.py     — DataTree: record storage, schema inference, GC
  DataBranch.py   — DataBranch: lazy DAG, projections, filtering, aggregation
  Schema.py       — Schema/Branch/Leaf, type hierarchy, infer_schema, Path
  utils.py        — isna helper
tests/
  test_sunbear.py       — Core test suite
  test_comprehensive.py — Extended tests (52 tests)
test.py                 — BlueSky feed exploration notebook
```

---

## License

MIT