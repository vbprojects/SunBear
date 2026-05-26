# SunBear Data Engine — v0.2.0 Specification

SunBear implements DataTrees, a lightweight lazy graph database for parsing and querying large amounts of JSON records. The API blends pandas and R dataframe syntax with tree-native operations like schema-aware filtering, multidimensional indexing, aggregation, and partitioning.

---

## 1. Architecture Overview

| Component | Role |
|-----------|------|
| **DataTree** | The base container. Holds a list of dict records, their inferred schemas, and a schema-to-record mapping. All mutations flow through lazy `DataBranch` views. |
| **DataBranch** | A lazy DAG node pointing to a `DataTree` or upstream `DataBranch`. Holds a callable `operation` and optional `projection_schema` / `projection_col`. Materialises only when `.collect()`, `len()`, or iteration is triggered. |
| **Schema** | A named tree of nodes (Branch/Leaf). Leaves carry types: `PrimitiveType`, `UnionType`, `ListType`, `FunctionType`, `NullType`, or `ThunkFunctionType`. |
| **Path** | Static helpers `Path.parse_depth` (dot-strings / tuples) and `Path.parse_breadth` (lists). |

---

## 2. Schemas

### 2.1 Types

| Type | Description |
|------|-------------|
| `PrimitiveType(cls)` | Wraps `int`, `str`, `float`, `bool`, etc. |
| `NullType()` | Represents `None` / missing field. |
| `UnionType(types)` | Set of types — flattens nested unions. |
| `ListType(item)` | List with an element schema. |
| `FunctionType(fn)` | Custom membership predicate. |
| `ThunkFunctionType(a, b, op)` | Logical combination (`and` / `or`) of two `FunctionType`s — evaluated lazily. |

### 2.2 Equivalence Rules

- **Type-invariant**: `(a=(b=int, c=str)) == (a=(b=str, c=int))` → `True`. Reconciled to `Union[int, str]`.
- **Null-invariant**: `(a=(b=int, c=str)) == (a=(b=int)) == (a=(b=int, c=None))` → `True`. Missing keys treated as `NullType`.
- **Name-sensitive**: `(a=(b=int, c=str)) == (a=(c=str, b=int, d=int))` → `False`. Keys must be subset-compatible.
- **Non-transitive**: $A = B$ and $B = C \not\Rightarrow A = C$. A warning is raised; reconciliation finds the minimum tree that re-establishes transitivity.

### 2.3 Schema Operations

- `schema.add(path, type)` — Insert a type at a path.
- `schema.delete(path, type=None)` — Remove a type or entire node. Nullifies rather than destroys if `type` is given.
- `schema.move(src, dst)` — Relocate a node.
- `schema.diff(other)` — Return a `Branch` containing only differing paths with combined types.
- `schema.reconcile(other)` — Produce the union superset (maximum type representation).

Operations on schemas are **lazy at the record level**: updating a schema does not iterate records. The mutation lives in a Projection Schema on the `DataBranch` and is applied on-the-fly during materialization.

### 2.4 Inferred vs. Projection Schemas

- **Inferred Schema** — Read-only structural truth of the data in memory.
- **Projection Schema** — A localised view applied to a `DataBranch`. When a user writes `A = A + (d=int)`, the engine generates a Projection Schema that injects `d=None` at materialization without touching the underlying records.

---

## 3. DataTree

### 3.1 Construction

```python
dt = DataTree(records, defer_evaluation=False)
```

- `records`: `List[Dict[str, Any]]` — each dict must have string keys.
- `defer_evaluation`: if `True`, schema inference is skipped until first materialization.

### 3.2 Internal State

| Attribute | Purpose |
|-----------|---------|
| `_schemas: Dict[int, Schema]` | Integer IDs → Schema objects. |
| `_record_schema_map: List[int]` | Per-record schema ID. |
| `_reconciled: bool` | `False` when non-transitive schemas coexist. |
| `stale: bool` | `True` when lazy mutations (tombstoned deletions) need flushing. |
| `_tombstones: List[bool]` | Sparse mask for deferred garbage collection. |

### 3.3 Schema Building (`build_schemas`)

Iterates records, calls `infer_schema`, checks subset-equivalence against existing schemas, reconciles when overlapping, assigns IDs. Tombstoned records are physically purged during this pass.

### 3.4 Deferred Garbage Collection

Record deletion marks a tombstone and sets `stale = True`. Schemas may temporarily hold zero-member counts. Only materializing calls (`.length()`, `.build_schemas()`, `.mat`) physically purge and prune.

---

## 4. DataBranch

### 4.1 Construction

```python
branch = DataBranch(source, operation=callable, projection_schema=optional)
```

- `source`: A `DataTree` or another `DataBranch`.
- `operation`: A callable `(records) -> records` applied during evaluation.
- `projection_schema`: Optional `Schema` for structural output bounds.

Key flags:
- `projection_col`: Set by `__getitem__` to track which field(s) are being projected.
- `return_tree`: If `True`, `.collect()` wraps output back into a `DataTree`.

### 4.2 Evaluation Pipeline

`evaluate_records()` walks the source chain recursively, then applies `self.operation`. `collect()` triggers this and applies `_apply_projection` if `projection_col` is set.

### 4.3 Core Methods

#### Filtering / Transformation

| Method | Behaviour |
|--------|-----------|
| `.shallow(func)` | Applies `func` to the projected value. If `func` returns `bool`, filters rows; otherwise mutates the value at the projected path inline. |
| `.deep(func)` | Recursively walks every leaf (scalar, list, dict) and applies `func`. |
| `.isna()` | Shorthand for `.shallow(isna)`. |
| `.not_(func)` | Negates a predicate. |
| `.assign(val)` | Sets the projected path(s) to `val` for every record. |

#### Aggregation / Partitioning

| Method | Behaviour |
|--------|-----------|
| `.group_by(target_node="members")` | Bins records by the projected column into `{"<key>": <value>, "members": [...]}` dicts. Detects list-valued paths mid-traversal and applies inner grouping. Returns a `DataBranch` with `return_tree=True`. |
| `.aggregate()` | Collects all non-`None` projected values into a single list under the path key. Records with `None` projections pass through unmodified. |
| `.add_path(dest, source_branch)` | Injects `source_branch`'s evaluated values at `dest`. `".."` wraps the record in a new root dict; `"."` is the root. Returns `return_tree=True`. |

#### Indexing: `__getitem__`

Two-dimensional: `dt[row, col]`.

**Row dimension:**
- `int` — single record.
- `slice` — range (lazy `islice` for generators).
- `list[int]` — specific indices.
- `dict` — schema pruning (only loads matching keys, streaming-friendly).
- `:` — all records.

**Column dimension:**
- `str` — depth traversal via dot-notation (e.g., `"post.record.text"`).
- `tuple` — explicit depth path (e.g., `("education", "degree")`).
- `list[str]` — breadth projection (e.g., `["name", "age"]`).
- `:` — no projection (return full records).

**List-of-records traversal:** When a depth path hits a `list` mid-traversal (e.g., `"post.record.facets.features"` where `facets` is a list of dicts), remaining path segments are mapped across each element, producing nested lists. This aligns with the spec: sub-DataTrees within records are queryable from the parent.

---

## 5. Extension System

Both `DataTree` and `DataBranch` support:

```python
@DataType.register_method
@DataBranch.register_method
def my_method(db, ...):
    return DataBranch(db, operation=lambda r: ...)
```

This registers the function as a method on both classes. Methods compose lazily — they return new `DataBranch` instances rather than mutating.

Built-in extensions registered at module load:
- `add_path`, `aggregate`, `group_by` (on `DataBranch`, auto-registered to `DataTree`)

---

## 6. Path Resolution

| Purpose | Syntax | Example |
|---------|--------|---------|
| Depth traversal | `str` (dot-notation) or `tuple` | `"post.record.text"`, `("education", "degree")` |
| Breadth projection | `list[str]` | `["name", "age", "occupation"]` |

---

## 7. Usage Patterns

### Streaming schema projection vs. post-hoc projection

```python
# Schema-enforced: only loads name and age — memory efficient for streaming
dt[{"name": Any, "age": Any}, :].collect()

# Post-hoc: loads full records, then extracts — simpler but memory-heavy
dt[:, ["name", "age"]].collect()
```

### Filtering and chaining

```python
dt.not(isna)[:, "age"].shallow(lambda x: x > 30)
dt.isna().length()
dt[:, "age"].not_(lambda x: x > 30)
dt.deep(isna).assign(1)
```

### Grouping and aggregation

```python
# Single-level group by
dt[:, "occupation"].group_by().collect()
# [{"occupation": "Engineer", "members": [...]}, {"occupation": "Manager", "members": [...]}]

# Chained group by (outer: city, inner: occupation within members)
dt[:, "city"].group_by()[:, "members.occupation"].group_by().collect()

# Dynamic path injection
db = dt[:, "occupation"].filter(lambda x: x == "Engineer")
db.add_path("..", db[:, "occupation"]).collect()
# [{"Engineer": {...}}, ...]

# Aggregate matching records under a common key
dt[:, "Engineer"].aggregate().collect()
# [{"Engineer": [{...}, {...}]}, ...unmatched records...]
```

### Sub-datatree traversal

```python
# facets is a list of dicts; .features is queried across each facet
dt[:, "post.record.facets.features"].collect()
# [[[{...}, ...]], [[{...}]], ...]
```

---

## 8. File Inventory

| File | Contents |
|------|----------|
| `src/DataTree.py` | `DataTree` class — record storage, schema inference, GC tombstones. |
| `src/DataBranch.py` | `DataBranch` class — lazy DAG, projections, filtering, aggregation, group_by, indexing. |
| `src/Schema.py` | `Path`, `Schema`, `Branch`, `Leaf`, type hierarchy, `infer_schema`. |
| `src/utils.py` | `isna` helper. |
| `tests/test_sunbear.py` | Core test suite. |
| `tests/test_aggregations.py` | Aggregation/partition tests. |