# Schema — Type-Level Schema Trees

The `Schema` module provides type-level schema trees for describing and
reconciling the structure of records. It consists of a **SchemaType hierarchy**
(leaf value types) and a **Node hierarchy** (tree structure).

**Key semantic rules** (from `schema_notes.md`):

1. **Type-Invariant** — `Leaf(int) == Leaf(str)` is `True`. All leaves are
   equivalent regardless of their contained type.
2. **Null-Invariant** — Missing fields are equivalent to `None`. Two branches
   are equivalent if one's field-name set is a subset of the other's.
3. **Not Name-Invariant** — Different field names break equivalence.
4. **Non-Transitive** — `A == B` and `B == C` does **not** imply `A == C`.

---

## SchemaType Hierarchy

These describe the type of a leaf value.

| Class | Description | Equality |
|---|---|---|
| `Primitive(type)` | Wraps a Python type (`int`, `str`, `float`, `bool`) | By identity: `Primitive(int) == Primitive(int)` |
| `NullType()` | Singleton for `None` / missing values | All instances equal (singleton) |
| `UnionType({types})` | Union of schema types. Auto-unpacks nested unions | By frozen set of types |
| `ListType(item_type)` | List with an item type | By item type |
| `CustomType(name, predicate)` | Named custom type with a membership predicate | By name |

```python
from sunbear import Primitive, NullType, UnionType, ListType, CustomType

t1 = Primitive(int)
t2 = UnionType({Primitive(int), Primitive(str)})
t3 = ListType(Primitive(float))
t4 = CustomType("positive_int", lambda x: isinstance(x, int) and x > 0)
t4.check(5)  # True
```

### `combine_types(a, b) -> SchemaType`
Combine two SchemaTypes. If equal, returns `a`; otherwise returns a union:

```python
from sunbear import combine_types, Primitive, NullType

combine_types(Primitive(int), NullType())  # Union{int, Null}
```

---

## Node Hierarchy

These form the schema tree.

| Class | Description | Equivalence Rule |
|---|---|---|
| `Leaf(type)` | Terminal node holding a SchemaType | **Type-invariant**: all leaves are equal |
| `Branch(fields)` | Named container with `Dict[str, Node]` children | **Null-invariant subset**: one field-set must be a subset of the other, overlapping fields must match |

```python
from sunbear import Leaf, Branch, Primitive

schema_tree = Branch({
    "name": Leaf(Primitive(str)),
    "age": Leaf(Primitive(int)),
    "address": Branch({
        "city": Leaf(Primitive(str)),
        "zip": Leaf(Primitive(int)),
    }),
})
```

### Branch Equivalence Examples

```python
a = Branch({"x": Leaf(Primitive(int)), "y": Leaf(Primitive(str))})
b = Branch({"x": Leaf(Primitive(int))})       # subset → equal
c = Branch({"x": Leaf(Primitive(int)), "z": Leaf(Primitive(float))})
d = Branch({"y": Leaf(Primitive(str)), "x": Leaf(Primitive(int))})

assert a == b   # null-invariant: missing "y" in b is OK
assert a != c   # different field names → not equal
assert a == d   # order doesn't matter
```

### Non-Transitive Equality

```python
a = Branch({"x": Leaf(Primitive(int)), "y": Leaf(Primitive(str))})
b = Branch({"x": Leaf(Primitive(int))})          # subset of a
c = Branch({"x": Leaf(Primitive(int)), "z": Leaf(Primitive(float))})

assert a == b and b == c   # True
assert a != c              # Also True! (a has "y", c has "z")
```

---

## Reconciliation

### `reconcile(branches: list[Branch]) -> Branch`
Given a list of pairwise-equivalent branches, return a single minimum tree
that represents the maximum of all. Missing fields are widened with
`Union[type, Null]`.

```python
from sunbear import reconcile

a = Branch({"x": Leaf(Primitive(int))})
b = Branch({"x": Leaf(Primitive(str)), "y": Leaf(Primitive(int))})

merged = reconcile([a, b])
# merged has {"x": Union[int, str], "y": int}
```

### `branch.reconcile_with(other: Branch) -> Branch`
Pairwise reconciliation on a Branch instance.

---

## Schema Inference

### `infer_schema(obj: Any) -> Node`
Recursively infer a schema tree from a Python object:

| Input | Result |
|---|---|
| `None` | `Leaf(NullType())` |
| `dict` | `Branch({k: infer_schema(v) for ...})` |
| `list` | `Leaf(ListType(inferred_item_type))` |
| Anything else | `Leaf(Primitive(type(obj)))` |

```python
from sunbear import infer_schema

node = infer_schema({"name": "Alice", "age": 30, "tags": ["a", "b"]})
# Branch({"name": Leaf(str), "age": Leaf(int), "tags": Leaf(List[str])})
```

---

## Schema Class — High-Level Interface

### Construction

```python
from sunbear import Schema

# From a single record
schema = Schema.from_record({"name": "Alice", "age": 30})

# From multiple records (reconciles automatically)
schema = Schema.from_records([
    {"name": "Alice", "age": 30},
    {"name": "Bob", "age": 25, "city": "NYC"},
])

# With a display name
schema = Schema(root_branch, name="users")
```

### Methods

| Method | Description |
|---|---|
| `schema.filter(records)` | Return only records that structurally match this schema |
| `schema.show(collapsed=False)` | Display schema: Unicode tree (terminal) or collapsible HTML (Jupyter) |
| `schema.type_stats(records)` | Compute per-leaf type ratios across records |
| `schema.root` | Access the root Branch |

---

## Visualization

Schema trees can be displayed in terminal or Jupyter:

```
Root
├── name : str
├── age  : int
└── address
    ├── city : str
    └── zip  : int
```

In Jupyter, `Schema.show()` renders a collapsible HTML tree with `<details>`
elements. The `collapsed=True` argument starts all sub-trees collapsed.

### `Schema.show_list(schemas, collapsed=False)`
Display a list of unreconcilable schemas. Useful when schema inference
reveals structural incompatibility (e.g., mixed Branch vs Leaf at the
same path).

---

## Integration with DataTree

```python
from sunbear import DataTree

dt = DataTree.from_records([{"a": 1}, {"a": 2}])
schema = dt.schema   # materializes, infers, reconciles
schema.show()
```

## Copy notebook paths as selectors

In IPython/Jupyter HTML output, click a field name to copy a paste-ready selector
such as `f['author']['id']`. Import `f` with `from sunbear import f`, then paste
into `select`, `assign`, or another expression. Bracket syntax preserves literal
dots, quotes, Python keywords, and names that collide with expression methods.
Nested list fields use explicit traversal, for example `f['posts'][...]['text']`.
Use `.as_('texts')` or `select(texts=...)` to project that nested value; positional
`select(path)` retains the complete top-level field under the existing contract.

Buttons support keyboard activation and announce copy status. Clicking a branch
name copies its selector; the disclosure arrow still expands or collapses it.
If clipboard permission is unavailable, the renderer attempts a legacy copy and
then exposes a selected input for manual copying. The **Copyable selectors**
section is always available for manual copying, including notebook frontends
that disable JavaScript or strip event handlers from untrusted output. No
notebook extension or new dependency is required.
