# SunBear

**A lazy, schema-aware JSON data engine — like pandas mixed with jq, built for tree-structured data.**

SunBear lets you query, filter, aggregate, and transform collections of JSON records using a concise Pythonic API. It infers schemas from your data, indexes records by schema variant, and chains lazy operations into a DAG that only materialises when you call `.collect()`.

---

## Quick Start

```python
from sunbear import DataTree

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
dt = DataTree(records)                          # infers schemas immediately
dt = DataTree(records, defer_evaluation=True)   # lazy — schemas built on first access
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

---

## API Reference

### `DataTree`

#### Constructor

```python
DataTree(records=None, defer_evaluation=False)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `records` | `list[dict]` or iterable | The JSON records to load. Can be a generator for streaming. |
| `defer_evaluation` | `bool` | If `True`, schema inference is deferred until first access. |

#### Properties & Methods

| Method | Returns | Description |
|--------|---------|-------------|
| `.mat` | `DataTree` | Materialized view — triggers GC and schema rebuild if stale. |
| `.schemas(materialize=True)` | `dict[int, Schema]` | Returns the schema map. |
| `.build_schemas()` | `self` | Forces schema inference over all records. |
| `.length()` | `int` | Number of records (triggers materialization). |
| `.show(collapsed=False)` | — | Pretty-print or display (IPython) the tree structure. |
| `.materialize()` | `DataTree` | Returns a materialized view (same as `.mat`). |

#### Indexing: `dt[row, column]`

SunBear uses 2D indexing:

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

When a depth path hits a list of dicts mid-traversal, remaining segments are mapped across each element:

```python
dt[:, "post.record.facets.features"].collect()
# → [[[{...}, ...]], [[{...}]], ...]
```

#### Chaining Methods (delegated to `DataBranch`)

These methods on `DataTree` create a `DataBranch` and delegate:

| Method | Description |
|--------|-------------|
| `.map_records(func)` | 1-to-1 record transformation |
| `.filter_records(func)` | Keep records where `func(record)` is truthy |
| `.flat_map_records(func)` | 1-to-N record expansion |
| `.shallow(func)` | Apply `func` to projected value (filter or mutate) |
| `.deep(func)` | Recursively walk every leaf in the record |
| `.isna()` | Filter to records where projected value is `None` |
| `.not_(func)` | Negate a predicate |
| `.assign(expr, **kwargs)` | Set projected path(s) to a value or expression |
| `.path(paths)` | Extract specific paths into a new dict per record |
| `.select(**kwargs)` | Select and rename paths (registered extension) |
| `.head(n=5)` | First N records (registered extension) |
| `.add_path(dest, source)` | Inject source values at a destination path |
| `.aggregate()` | Collect non-`None` projected values into a list |
| `.group_by(target_node)` | Bin records by projected column |
| `.explode()` | Unnest list-valued columns into multiple rows |

---

### `DataBranch`

#### Constructor

```python
DataBranch(source, operation=None, projection_schema=None)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `source` | `DataTree` or `DataBranch` | The upstream data source. |
| `operation` | `callable` or `None` | A lazy transformation applied on evaluation. |
| `projection_schema` | `Schema` or `None` | Optional schema hint for the branch. |

#### Core Primitives

These three atomic operations form the foundation of all transformations:

**`map_records(func, copy=True)` → `DataBranch`**

1-to-1 record transformation. `func` receives a single record dict and returns a transformed dict.

```python
dt.map_records(lambda r: {**r, "age": r["age"] * 2}).collect()
```

**`filter_records(func)` → `DataBranch`**

Keep only records where `func(record)` is truthy.

```python
dt.filter_records(lambda r: r["age"] > 30).collect()
```

**`flat_map_records(func, copy=True)` → `DataBranch`**

1-to-N expansion. `func` receives a record and returns an iterable of records.

```python
dt.flat_map_records(lambda r: [r, {**r, "duplicate": True}]).collect()
```

#### Evaluation & Materialization

| Method | Returns | Description |
|--------|---------|-------------|
| `.collect()` | `list` or `DataTree` | Evaluate the branch. If `return_tree=True`, returns a `DataTree`. |
| `.materialize()` | `DataTree` | Evaluate and wrap result in a materialized `DataTree`. |
| `.evaluate_records()` | iterable | Internal — walk the DAG and yield transformed records. |
| `.schemas(materialize=True)` | `dict[int, Schema]` | Schema inference for the branch output. |
| `.length()` | `int` | Number of records after evaluation. |

#### Filtering & Transformation

**`shallow(func)` → `DataBranch`**

Apply `func` to the projected value of each record.

- If `func` returns a `bool`: acts as a filter (keep/discard the record).
- If `func` returns a non-bool: acts as a mutation (replaces the projected value in-place).

```python
# Filter: keep records where age > 30
dt[:, "age"].shallow(lambda x: x > 30).collect()

# Mutate: double all ages
dt[:, "age"].shallow(lambda x: x * 2).collect()
```

**`deep(func)` → `DataBranch`**

Recursively walk every leaf in the record tree and apply `func`.

- If `func` returns a `bool`: leaf is kept if truthy, replaced with `None` if falsy.
- If `func` returns a non-bool: leaf value is replaced.

```python
# Replace all ints with int*10
dt.deep(lambda x: x * 10 if isinstance(x, int) else x).collect()

# Nullify ints <= 2
dt.deep(lambda x: x if isinstance(x, int) and x > 2 else None).collect()
```

**`isna()` → `DataBranch`**

Shorthand for `.shallow(isna)` — filter to records where the projected value is `None`.

```python
dt[:, "optional_field"].isna().collect()
```

**`not_(func)` → `DataBranch`**

Negate a predicate. Equivalent to `.shallow(lambda x: not func(x))`.

```python
dt[:, "age"].not_(lambda x: x > 30).collect()  # ages <= 30
```

#### Assignment

**`assign(expr=None, **kwargs)` → `DataBranch`**

Set projected path(s) to a value or expression.

*Case A — Context-aware (after `[:, path]`):*
```python
dt[:, "new_field"].assign("literal_value")
dt[:, "new_field"].assign(col("source.path"))
```

*Case B — Keyword arguments:*
```python
dt.assign(new_uri=col("post.uri"), text_copy=col("post.record.text"))
```

The value can be:
- A literal (assigned as-is)
- An `Expression` object (evaluated per-record via `.evaluate(record)`)

#### Path Extraction

**`path(paths)` → `DataBranch`**

Resolve one or more paths and return a new dict per record keyed by the final path segment.

```python
dt.path("post.record.text").collect()
# → [{"text": "hello"}, {"text": "world"}, ...]

dt.path(["post.uri", "post.record.createdAt"]).collect()
# → [{"uri": "...", "createdAt": "..."}, ...]
```

#### Selection (Registered Extension)

**`select(**kwargs)` → `DataBranch`**

Select and rename paths in a single pass. Each keyword maps a new name to a source path.

```python
dt.select(
    uri="post.uri",
    text=col("post.record.text"),
    likes="post.record.stats.likes"
).collect()
```

This is syntactic sugar for chaining `[:, k].assign(v)` for each kwarg, then `.path(list(kwargs.keys()))`.

#### Aggregation & Partitioning

**`group_by(target_node="members")` → `DataBranch`**

Bins records by the projected column value. Detects list-valued paths and applies inner grouping.

```python
dt[:, "occupation"].group_by().collect()
# → [{"occupation": "Engineer", "members": [...]}, ...]

# Chained group-by (outer: city, inner: occupation)
dt[:, "city"].group_by()[:, "members.occupation"].group_by().collect()
```

**`aggregate()` → `DataBranch`**

Collects non-`None` projected values into a single list under the path key. Records where the projection is `None` pass through unaltered.

```python
dt[:, "tags"].aggregate().collect()
```

**`add_path(dest, source_branch)` → `DataBranch`**

Injects values from a source branch at a destination path. Use `".."` as the destination to wrap the record in a new root dict keyed by the source value.

```python
db = dt[:, "occupation"].filter(lambda x: x == "Engineer")
db.add_path("..", db[:, "occupation"]).collect()
# → [{"Engineer": {...}}, ...]
```

**`explode()` → `DataBranch`**

Unnests the first list-valued column in a breadth projection into multiple rows.

```python
dt[:, ["tags", "name"]].explode().collect()
# Each tag becomes its own row with the corresponding name
```

#### Indexing: `branch[row, column]`

Same 2D indexing as `DataTree`. Row selectors filter records; column selectors project fields.

```python
branch[:, "name"]           # project name
branch[0:5, ["a", "b"]]    # first 5 records, columns a and b
branch[:, :]                # all records, no projection
```

#### Display

| Method | Description |
|--------|-------------|
| `.show(collapsed=False)` | Pretty-print or display (IPython) the branch structure. |
| `str(branch)` | String representation. |
| `_repr_html_()` | HTML representation for Jupyter notebooks. |

---

### `Schema` Module (`sunbear.Schema`)

#### Types

| Class | Description |
|-------|-------------|
| `PrimitiveType(type_class)` | A primitive Python type (`int`, `str`, `float`, etc.) |
| `NullType()` | Represents `None` / missing values |
| `UnionType(types)` | A union of possible types |
| `ListType(item_schema)` | A list of items with a given schema |
| `FunctionType(func)` | A custom membership function |
| `ThunkFunctionType(func_a, func_b, operator)` | Deferred logical combination of functions |

#### Nodes

| Class | Description |
|-------|-------------|
| `Leaf(schema_type)` | A leaf node holding a `SchemaType` |
| `Branch(fields)` | A branch node holding a dict of child nodes |
| `Schema(fields, is_projection=False)` | A named branch representing the shape of data |

#### Branch Operations

| Method | Description |
|--------|-------------|
| `.reconcile(other)` | Create a union of two subset-equivalent branches |
| `.diff(other)` | Return a branch containing only the differing paths |
| `.add(path, schema_type)` | Immutably add a type at a path |
| `.delete(path, schema_type=None)` | Immutably delete a type or node at a path |
| `.move(source_path, dest_path)` | Immutably move a node from source to destination |
| `.show(collapsed=False)` | Display the branch structure |

#### Utility Functions

| Function | Description |
|----------|-------------|
| `infer_schema(obj)` | Infer a schema tree from any Python object |
| `schema_diff(schema1, schema2)` | Alias for `schema1.diff(schema2)` |
| `combine_types(a, b)` | Combine two schema types into a union |

---

### `utils` Module (`sunbear.utils`)

| Function | Description |
|----------|-------------|
| `isna(val)` | Check if a value is `None` |
| `resolve_path(val, path_segments)` | Traverse a nested dict/list structure by path segments |
| `set_path(record, path_segments, value)` | Set a value in a nested dict, creating missing paths |

#### Expression System

| Class | Description |
|-------|-------------|
| `Expression` | Base class for symbolic evaluators. Subclass and implement `.evaluate(record)`. |
| `col(path_str)` | Symbolic evaluator for a column/path. Evaluates to the resolved value at that path. |

```python
from sunbear.utils import col

expr = col("post.record.text")
expr.evaluate({"post": {"record": {"text": "hello"}}})
# → "hello"
```

---

## Extension System

SunBear supports dynamic method registration on both `DataTree` and `DataBranch`:

```python
from sunbear import DataTree, DataBranch

@DataTree.register_method
@DataBranch.register_method
def head(db, n=5):
    """Return the first N records."""
    import itertools
    from sunbear.DataBranch import DataBranch
    dbt = DataBranch(db, operation=lambda r: list(itertools.islice(r, n)))
    dbt.return_tree = True
    return dbt

# Now usable on both DataTree and DataBranch:
dt.head(n=10).collect()
dt[:, "name"].head(n=3).collect()
```

You can also load all public functions from a module:

```python
DataTree.load_extensions(my_module)
DataBranch.load_extensions(my_module)
```

---

## Why Schema Non-Transitivity Matters

SunBear is designed for messy, semi-structured data. In real datasets, optional fields often appear as `None` in some records and as nested objects in others. That can create **non-transitive schema equality**: two schemas may each be compatible with an intermediate schema, but not with each other.

Example:

```python
from sunbear import DataTree

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

Here we cannot infer a single structure for all records. Record 2 is missing fields, and records 1 and 3 have different nested structures under `label`. This means we have multiple distinct schemas, and we must reconcile them to gain a unified view.

A dataset with a single schema can be converted to tidy data, which is ideal for analysis. Multiple schemas can be reconciled by taking the union of all fields and treating missing keys as `None`. The point is that we want to eventually turn tree-based data into tabular data, and we need to reason about the structure of the data to do that.

---

## Design Principles

1. **Lazy by default**: Operations build a DAG; nothing materializes until `.collect()`.
2. **Immutable**: Every operation returns a new object; sources are never mutated.
3. **Schema-aware**: The engine understands data structure and uses it for optimization and validation.
4. **Composable**: Three core primitives (`map_records`, `filter_records`, `flat_map_records`) form the foundation for all higher-level operations.
5. **Expression-based**: The `Expression` system (`col`, custom evaluators) lets you reference data paths without writing lambdas.
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