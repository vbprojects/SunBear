# Schema — Type-Level Schema Trees for SunBear

The `Schema` module defines a **type-level schema tree** that describes the structure of records. It is a tree where **nodes are names** and **leaves are types**, with rich equivalence semantics.

## SchemaType Hierarchy

The leaf-level type descriptors:

```
SchemaType
├── Primitive(int, str, float, bool, ...)   # wraps a Python type
├── NullType()                               # singleton for None/missing
├── UnionType({int, str})                    # union of types (auto-flattens)
├── ListType(Primitive(str))                 # list with item type
└── CustomType("PositiveInt", predicate)     # named type with membership test
```

### Key Properties

- **`Primitive`** — wraps a Python type. Equality is by identity: `Primitive(int) == Primitive(int)` is `True`, `Primitive(int) != Primitive(str)` is `False`.
- **`NullType`** — singleton sentinel. All `NullType()` instances are the same object.
- **`UnionType`** — auto-flattens nested unions. `UnionType({UnionType({int, str}), float})` → `UnionType({int, str, float})`.
- **`ListType`** — wraps an item type. `ListType(Primitive(str))` for `list[str]`.
- **`CustomType`** — named type with a predicate. Equality is by **name only** (predicates can't be compared).

### `combine_types`

```python
combine_types(a: SchemaType, b: SchemaType) -> SchemaType
```

If `a == b`, returns `a`. Otherwise returns `UnionType({a, b})`.

## Node Hierarchy

The schema tree nodes:

```
Node
├── Leaf(type: SchemaType)     # terminal — holds a SchemaType
└── Branch(fields: Dict[str, Node])  # named container
```

### `Leaf` — Type-Invariant Terminal

```python
Leaf(Primitive(int)) == Leaf(Primitive(str))  # → True  (TYPE-INVARIANT)
Leaf(Primitive(int)) == Leaf(NullType())      # → True
Leaf(Primitive(int)) == Leaf(ListType(...))   # → True
```

**All leaves are equivalent** — `__eq__` always returns `True`. This is the **type-invariance** property: the schema cares about **structure**, not the specific leaf type.

All leaves hash to `0` — they can be used as dict/set keys without collision.

### `Branch` — Subset-Equivalence Container

```python
Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
```

Branch equivalence has three key properties:

#### 1. NULL-INVARIANCE

Missing fields are equivalent to `None`:

```python
Branch({"a": int, "b": str}) == Branch({"a": int})  # → True
```

A branch with fewer fields is a **subset** of a branch with more fields.

#### 2. NAME-INVARIANCE

Different field names **break** equivalence:

```python
Branch({"a": int, "b": str}) != Branch({"a": int, "c": str})  # → False
```

The field name set must have a **subset relationship** (one is subset of the other).

#### 3. NON-TRANSITIVITY

```python
A = Branch({"a": int, "b": int})
B = Branch({"b": int})
C = Branch({"b": int, "c": int})

A == B  # → True (B is subset of A)
B == C  # → True (B is subset of C)
A == C  # → False (no subset relationship — A has "a", C has "c")
```

$A = B$ and $B = C \not\Rightarrow A = C$. This is the **defining property** of schema equivalence.

### Reconciliation

When schemas are non-transitive, `reconcile` finds the **minimum union tree**:

```python
reconcile([branch_a, branch_b, ...]) → Branch
```

Algorithm:
1. Start with the first branch
2. Pairwise merge with each subsequent branch
3. For overlapping fields: **widen types** (combine with `UnionType`)
4. For missing fields: **widen to Union[type, Null]**

```python
_reconcile_pair(a, b):
    all_keys = set(a.fields) | set(b.fields)
    for k in all_keys:
        if k in both:
            if both are Branch: recurse
            if both are Leaf: combine_types
        if k in a only: widen to Union[type, Null]
        if k in b only: widen to Union[type, Null]
```

## Schema Inference

```python
infer_schema(obj: Any) -> Node
```

| Value | Schema |
|-------|--------|
| `None` | `Leaf(NullType())` |
| `dict` | `Branch({k: infer_schema(v) for k, v in ...})` |
| `list` | `Leaf(ListType(inferred_item_type))` |
| anything else | `Leaf(Primitive(type(obj)))` |

### `Schema` — High-Level Interface

```python
Schema(root: Branch, name: Optional[str] = None)
```

- `from_record(record)` — infer from a single dict
- `from_records(records)` — infer + reconcile from multiple
- `filter(records)` — return only structurally matching records
- `show()` — auto-detect IPython or fall back to `print`
- `type_stats(records)` — per-leaf type ratios across records

### `SchemaList`

Container for **unreconcilable** schemas — returned when `inspect` finds variants that cannot be merged.

## Visualization

- `_tree_lines()` — Unicode box-drawing tree for terminal
- `_repr_html_()` — collapsible HTML for Jupyter
- `show(collapsed=True)` — compact display mode

## Type Statistics

```python
schema.type_stats(records) → {"path": {"type": ratio, ...}}
```

Walks the schema tree and counts per-leaf type occurrences across records, including `Null` for missing values.