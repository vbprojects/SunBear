# Expr — Declarative Expression Builder

The `expr` module provides a declarative API for building DataTree
transformations. Expressions are composed from AST nodes (literals, column
references, operators), compiled to per-record closures, and lowered to
DataTree operations.

---

## Quick Reference

```python
from sunbear.expr import b, _, assign, keep, fork, case, filter_field, map_field, flatten
from sunbear.expr import select, rename, drop, default, unnest, assert_, coalesce, sbo
from sunbear.expr.sbo import chain

dt.expr(
    assign(b.status, "active"),                    # set constant (positional)
    assign(b.normalized, (b.age - mu) / std),      # computed field (positional)
    assign(status="active", score=0),               # keyword sugar — multiple assigns
    keep(b.age >= 18),                              # row filter
    assign(b.summary, sbo.flatten(b.tags, -1)),     # flatten list
    assign(b.valid, sbo.filter(b.items, lambda x: x > 0)),  # filter list
    assign(b.lengths, sbo.map(b.tags, len)),         # map over list
    fork(b.is_adult,                                 # conditional branch
        then_block=(assign(b.tier, "adult"),),
        else_block=(assign(b.tier, "minor"),),
    ),
)

# Project / rename — keep only selected fields
dt.expr(*select(b.author, tags=b.commit.record.tags))

# Structural ops
dt.expr(*rename(name="full_name"))           # move field
dt.expr(drop(b.temp, b.internal))            # remove fields
dt.expr(default(b.tier, "standard"))         # fill missing values
dt.expr(unnest(b.address))                   # flatten nested dict

# Conditional ops
dt.expr(assert_(b.age >= 0, "negative age"))  # validate data
dt.expr(mask(b.flag, b.age < 18, "minor"))    # conditional set

# Sugar
dt.expr(coalesce(b.nickname, b.name, target=b.display))

# Path sugar (outside function calls)
stmt = b.x |= some_expr   # equivalent to assign(b.x, some_expr)
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

### `assign(target, value)` / `assign(**kwargs)`

Set a field to a computed value. Target and value are auto-wrapped if not
already Expr nodes.

**Positional form** (single assign):
```python
assign(b.status, "active")             # constant
assign(b.z_score, (b.x - mu) / std)    # computed
```

**Keyword form** (multiple assigns in one call):
```python
assign(tags=b.commit.record.tags, createdAt=b.commit.record.createdAt)
# equivalent to:
# assign(b.tags, b.commit.record.tags),
# assign(b.createdAt, b.commit.record.createdAt),
```

**`|=` sugar** (outside function calls, returns a statement tuple):
```python
stmt = b.tags |= sbo.flatten(b.tags, -1)
# equivalent to: assign(b.tags, sbo.flatten(b.tags, -1))
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

### `select(*args, **kwargs)`

Project / rename fields, then discard everything not selected. Returns a
**list** of statement tuples — unpack with `*select(...)`.

**Keyword args** move the source path to the kwarg key:
```python
# Move commit.record.tags → tags, commit.record.createdAt → createdAt
dt.expr(*select(tags=b.commit.record.tags, createdAt=b.commit.record.createdAt))
# result: each row has only {tags: ..., createdAt: ...}
```

**Positional args** keep the field at its current path (top-level key):
```python
dt.expr(*select(b.author))
# result: each row has only {author: ...}
```

**Mixed:**
```python
dt.expr(*select(b.author, tags=b.commit.record.tags))
# result: each row has {author: ..., tags: ...}
```

Use with `Program`:
```python
prog = Program().expr(
    *select(b.author, tags=b.commit.record.tags),
    keep(b.tags != None),
    assign(b.tags, sbo.flatten(b.tags)),
)
```

### `rename(**mapping)` — Structural

Move fields: old keys are removed, values are placed at new keys.

```python
rename(name="full_name")              # move name → full_name
rename(name="full_name", age="years")  # multiple renames
```

### `drop(*paths)` — Structural

Remove fields from each row:

```python
drop(b.temp, b.internal_id)
```

### `copy_field(src, dst)` — Structural

Duplicate a field value to a new path (source is kept):

```python
copy_field(b.name, b.backup)
```

### `default(target, value)` — Structural

Set a field only if it is currently `None` (missing). Unlike `assign`,
this does **not** overwrite existing values:

```python
default(b.tier, "standard")     # only set if tier is None
default(b.score, 0)             # fill missing scores with 0
```

### `nest(*paths, into=)` — Structural

Group fields into a nested dict. The source fields are removed:

```python
nest(b.first, b.last, into="name")
# {first: "Alice", last: "Smith"} → {name: {first: "Alice", last: "Smith"}}
```

### `unnest(path)` — Structural

Flatten a nested dict into top-level fields. The nested field is removed:

```python
unnest(b.address)
# {address: {city: "NY", zip: "10001"}} → {city: "NY", zip: "10001"}
```

### `assert_(pred, message=None)` — Conditional

Raise `ValueError` on the first row where the predicate is falsy. The optional
message replaces the default error text. Use `keep()` to filter rows:

```python
assert_(b.age >= 18)                    # raise with a default message
assert_(b.age >= 0, "negative age")     # raise with a custom message
keep(b.age >= 18)                       # filter underage rows
```

### `mask(target, pred, value)` — Conditional

Set `target` to `value` only where `pred` is true; leave it unchanged
(or `None` if absent) otherwise:

```python
mask(b.tier, b.age < 18, "minor")       # set tier="minor" for underage only
mask(b.flag, b.active == True, "on")
```

### Sugar ops

Common string/numeric/type transformations as single-statement shortcuts:

```python
cast(b.age, str)            # type coercion: int(b.age) or str(b.age), etc.
upper(b.name)               # "alice" → "ALICE"
lower_str(b.name)           # "ALICE" → "alice"
trim(b.name)                # "  hello  " → "hello"
round_field(b.score, 2)     # 85.123 → 85.12
```

### `coalesce(*paths, target=)` — Sugar

Assign the first non-`None` value among the source paths to `target`:

```python
coalesce(b.nickname, b.name, target=b.display)
# Alice: nickname=None → picks name="Alice"
# Bob:   nickname="Bobby" → picks nickname
```

### Chaining example

All ops compose freely with each other and with `assign`/`keep`:

```python
prog = Program().expr(
    unnest(b.address),
    coalesce(b.nickname, b.name, target=b.display),
    *select(b.display, b.city, b.score),
    round_field(b.score, 0),
    upper(b.city),
    keep(b.score >= 50),
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
