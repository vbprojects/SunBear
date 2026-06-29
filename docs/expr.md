# Expr — Declarative Expression Builder

The `expr` module provides a declarative API for building DataTree
transformations. Expressions are composed from AST nodes (literals, column
references, operators), compiled to per-record closures, and lowered to
DataTree operations.

---

## Quick Reference

```python
from sunbear.expr import b, _, assign, keep, fork, case, filter_field, map_field, flatten
from sunbear.expr import sbo
from sunbear.expr.sbo import chain

dt.expr(
    assign(b.status, "active"),                    # set constant
    assign(b.normalized, (b.age - mu) / std),       # computed field
    keep(b.age >= 18),                               # row filter
    assign(b.summary, sbo.flatten(b.tags, -1)),      # flatten list
    assign(b.valid, sbo.filter(b.items, lambda x: x > 0)),  # filter list
    assign(b.lengths, sbo.map(b.tags, len)),         # map over list
    fork(b.is_adult,                                 # conditional branch
        then_block=(assign(b.tier, "adult"),),
        else_block=(assign(b.tier, "minor"),),
    ),
)
```

---

## AST Nodes

| Node | Description |
|---|---|
| `Lit(value)` | Literal value (numbers, strings, lambdas, etc.) |
| `Col(indexer)` | Leaf reference to a record path (string indexer) |
| `Path(indexer)` | Lazy path built via `b.a.b.c` attribute access |
| `BinOp(op, left, right)` | Binary operation (`+`, `-`, `*`, `/`, `<`, `==`, `&`, `\|`, ...) |
| `UnOp(op, operand)` | Unary operation (`~` for `not`) |
| `Call(name, args, kwargs)` | Value-tier op call (compiles to `FUNCS[name](...)`) |
| `Placeholder()` | The `_` token used inside `chain()` |

---

## `b` — Lazy Namespace

`b` builds `Path` instances lazily via attribute access:

```python
from sunbear.expr import b

b.name              # Path("name")
b.profile.age       # Path("profile.age")
b["tags"]           # Path("tags")
b["complex.key"]    # Path("complex.key")
```

At evaluation time, `Path("a.b.c")` behaves identically to `Col("a.b.c")` —
it calls `record.get("a.b.c")`.

### `_` — Placeholder

The `_` singleton is a placeholder used in `chain()` for build-time AST
substitution:

```python
from sunbear.expr import _
```

---

## Statement Builders

These return tuples consumed by `DataTree.expr()` and `Program.expr()`.

### `assign(target, value)`

Set a field to a computed value. Target and value are auto-wrapped if not
already Expr nodes.

```python
assign(b.status, "active")             # constant
assign(b.z_score, (b.x - mu) / std)    # computed
```

### `keep(pred)`

Filter rows where the predicate evaluates to `True`:

```python
keep(b.age >= 18)
keep((b.age >= 18) & (b.status == "active"))
```

### `filter_field(target, pred)`

Intra-record lazy filter on a list field. Uses metadata skip-flags.

```python
filter_field(b.items, lambda x: x > 0)
```

### `map_field(target, fn)`

Map a function over each element of a list field:

```python
map_field(b.tags, lambda t: t.upper())
```

### `flatten(target, level=-1)`

Flatten a nested list structure. `level=-1` flattens fully.

```python
flatten(b.tags, -1)
flatten(b.matrix, 1)    # flatten one level
```

### `fork(cond, then_block, else_block)`

Conditional branch — applies different statements based on `cond`:

```python
fork(
    b.age >= 18,
    then_block=(assign(b.tier, "adult"), assign(b.can_vote, True)),
    else_block=(assign(b.tier, "minor"),),
)
```

### `case(*clauses, default=())`

Multi-way branch — evaluates clauses in order and applies the first match:

```python
case(
    (b.age >= 65, (assign(b.tier, "senior"),)),
    (b.age >= 18, (assign(b.tier, "adult"),)),
    default=(assign(b.tier, "minor"),),
)
```

---

## sbo — Value-Tier Ops

These build `Call` AST nodes that compile to FUNCS registry calls at runtime.

| Function | Description |
|---|---|
| `sbo.flatten(value, level=-1)` | Flatten nested list |
| `sbo.filter(value, pred)` | Filter list elements (lazy, uses meta skip-flags) |
| `sbo.map(value, fn)` | Map over list elements |
| `sbo.reduce(value, fn, init=MISSING)` | Fold/reduce over list |
| `sbo.length(value)` | Length of a list/string/collection |

```python
from sunbear.expr import b, assign, sbo

dt.expr(
    assign(b.flat, sbo.flatten(b.tags, -1)),
    assign(b.good, sbo.filter(b.items, lambda x: x > 0)),
    assign(b.upper, sbo.map(b.names, str.upper)),
    assign(b.total, sbo.reduce(b.amounts, lambda a, r: a + r.get("val"), 0)),
)
```

### `chain(seed, *steps)`

Build-time AST substitution pipeline. The `_` placeholder is replaced with
the accumulated expression at each step.

```python
from sunbear.expr.sbo import chain
from sunbear.expr import _

chain(
    sbo.flatten(b.tags, -1),                    # step 0: no _
    sbo.filter(_, lambda x: isinstance(x, str)), # step 1: _ = flattened
    sbo.map(_, str.upper),                       # step 2: _ = filtered
)
```

---

## Compilation

`compile(node: Expr) -> (record) -> value` walks the AST and produces a
per-record closure:

| Node | Closure |
|---|---|
| `Lit(v)` | `lambda r: v` |
| `Col(ix)` / `Path(ix)` | `lambda r: r.get(ix)` |
| `BinOp(op, L, R)` | `lambda r: op(L(r), R(r))` |
| `UnOp(op, operand)` | `lambda r: op(operand(r))` |
| `Call(name, args, kwargs)` | `lambda r: FUNCS[name](*[a(r) ...], **kwargs)` |

### Operator Table (`OPS`)

```python
OPS = {
    "+": lambda a, b: a + b,
    "-": lambda a, b: a - b,
    "*": lambda a, b: a * b,
    "/": lambda a, b: a / b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "&": lambda a, b: bool(a) and bool(b),   # logical and
    "|": lambda a, b: bool(a) or bool(b),    # logical or
    "~": lambda a: not a,                     # logical not
}
```

### FUNCS Registry

`register_func(name, fn)` registers runtime functions for Call nodes.
Pre-registered: `flatten`, `filter`, `map`, `reduce`, `length`.

---

## Lowering

`run_expr(dt, *statements)` applies statements to a DataTree:

| Statement | Lowers to |
|---|---|
| `assign(target, value)` | `dt.assign_at(target, closure)` |
| `keep(pred)` | `dt.filter(lambda r, m: bool(closure(r)))` |
| `filter_field(target, pred)` | `dt.assign_at(target, FUNCS["filter"](value, pred))` |
| `map_field(target, fn)` | `dt.assign_at(target, FUNCS["map"](value, fn))` |
| `flatten(target, level)` | `dt.assign_at(target, FUNCS["flatten"](value, level))` |
| `fork(...)` | `dt.apply(branch_fn)` — full-record copy + branch |
| `case(...)` | `dt.apply(case_fn)` — full-record copy + multi-branch |

```python
from sunbear.expr.lower import run_expr

result = run_expr(dt, assign(b.x, 1))
```
