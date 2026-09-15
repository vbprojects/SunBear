# Fluent syntax

```python
import sunbear as sb
from sunbear import f, selectors as cs
```

`DataTree` and immutable `Program` share the same row-local methods and compiler.
Program methods return a new definition. Expression builders run at construction;
value callbacks run per matching row/item. Python callbacks used with caching
require an explicit `cache_version` that covers code and captured dependencies.

## Row operations

| Operation | Contract |
|---|---|
| `.where(*predicates)` | Keep rows satisfying all predicates, short-circuiting left to right |
| `.where_any(*predicates)` | Keep rows satisfying any predicate, short-circuiting |
| `.reject(*predicates)` | Drop rows satisfying every supplied predicate |
| `.select(*fields, **named)` | Atomic projection: all RHSs see the input row |
| `.assign(**fields)` | Sequential assignment: later fields see earlier assignments |
| `.set(path, expression)` | Assign one nested path |
| `.update(path, builder)` | Invoke `builder(field_expression)` once and assign its result |
| `.drop(*paths)`, `.rename(old="new")`, `.copy(src, dst)` | Declarative path edits with isolated nested containers |
| `.nest(*paths, into=...)` | Group selected fields into an object |
| `.unnest(path, prefix="")` | Expand an object; reject destination collisions |
| `.require(predicate, message=None)` | Always raise a contextual error on failure |
| `.require_fields(*paths)` | Require presence; explicit null remains present |
| `.drop_nulls(*paths)` | Filter rows with missing or null selected values; defaults to all present fields |
| `.pipe(transform)` | Pass the tree or definition to a callable |
| `program.then(other)` | Append another Program's statements; the receiving Program's cache configuration applies |

`select(x=f.y, y=f.x)` swaps fields. `assign(x=f.y, y=f.x)` assigns the old `y`
to both fields. Named projection keys and `.as_("name")` aliases are **literal**
keys. Assignment keywords retain the existing dotted-path convention. For
compatibility, positional `select(f.address.city)` keeps the complete `address`
object; use `select(city=f.address.city)` for a leaf. Duplicate projected names
raise when a row is evaluated. `select()` requires at least one field.

Paths: `f.profile.name` traverses nested objects; `f["literal.key"]` addresses one
literal key; `f.items[0].price` indexes a list. Use bracket access for fields
named `str`, `list`, `obj`, `apply`, or any expression method. `sb.field("a.b")`
constructs a dotted path dynamically.

```python
flagged = (
    sb.Program()
    .when(f.score >= 10)
    .then(sb.Program().assign(label="high"))
    .otherwise(sb.Program().assign(label="low"))
)
```

Use `.end()` after `.then(...)` for no else branch. Branches support the same
row-local statements, including filtering and assertions.

## Values, null, and missing

`sb.lit(value)`, `sb.object(**expressions)`, and `sb.array(*expressions)` build
values. Object constructors omit `MISSING` members; arrays reject missing
elements. No output codec silently stringifies unsupported values.

`exists()`, `is_missing()`, `is_null()`, `is_not_null()`, `fill_missing(value)`,
`fill_null(value)`, and `coalesce(*values)` preserve the missing/null distinction.
`sb.coalesce(*values)` also selects the first non-missing, non-null value.
Fallbacks and conditional branches evaluate only when needed.

```python
label = sb.when(f.name.is_not_null()).then(f.name.str.strip()).otherwise("anonymous")
kind = sb.match(f.type).case("reply", "conversation").case("post", "original").otherwise("other")
```

Use `(f.age >= 18) & f.active` or `sb.all_of(...)`; use `|`/`sb.any_of(...)` and
`~`/`sb.not_(...)` for alternatives and negation. Python `and`, `or`, `not`, and
truth-testing expressions raise. Python `len(expr)` is deliberately unsupported.
Predicates that can be missing should guard presence or fill a default.

`is_in(values)`, `not_in(values)`, and `between(low, high, closed="both")` compose
predicates; `closed` also accepts `left`, `right`, `none`. `replace(mapping,
default=...)` maps values, preserving unmapped values when no default is given.
`cast(str/int/float/bool, errors="raise"/"null")` uses Python conversion semantics
(including Python's truth conversion for `bool`). `apply(fn)` is the explicit
Python value callback escape hatch.

New typed string/list/object/numeric operations propagate null and missing
separately and reject wrong input types. They do not silently coerce strings to
lists. Existing low-level `sbo` operations retain their historical behavior.

## Strings

Use `.str.lower()`, `upper`, `title`, `capitalize`, `casefold`, `strip`, `lstrip`,
`rstrip`, `normalize_whitespace`, `contains`, `starts_with`, `ends_with`,
`matches`, `replace`, `replace_all`, `remove_prefix`, `remove_suffix`, `split`,
`split_lines`, `partition`, `extract`, `extract_all`, `slice`, `head`, `tail`,
`len`, `pad_left`, `pad_right`, and `zfill`.

Matching/replacement is literal unless `regex=True`; `matches` is regex full
matching. Regexes must be static strings and compile before source consumption.
`replace` changes one occurrence by default; `replace_all` changes every
occurrence. `extract(pattern, group=0)` returns null on no match. String length
and slicing use Python Unicode code points, not grapheme clusters.
`sb.concat_str(*values, sep="")` joins expressions with null/missing propagation;
`sb.format_str("{}: {}", f.id, f.text)` uses positional Python formatting.

## Lists and item scope

Use `.list.len()`/`count`, `first`, `last`, `get`, `slice`, `head`, `tail`, `map`,
`filter`, `flat_map`, `flatten`, `contains`, `any`, `all`, `count_where`, `is_empty`,
`drop_nulls`, `unique`, `sort`, `sort_by`, `reverse`, `sum`, `mean`, `min`, `max`,
`reduce`, `concat`, `append`, `prepend`, `zip`, `enumerate`, `chunk`, `join`,
`union`, `intersection`, and `difference`. Apply `.list` at each new expression
in a chain. These operate within one row, so a large list still occupies memory.

```python
entry = sb.item("entry")
prices = (
    f.items.list.filter(entry.price <= f.budget)
    .list.map(entry.price * 2)
)
```

`f` always refers to the surrounding row. A single free item symbol is inferred;
use `item=entry` when the body has zero or multiple free symbols. Nested lists
must use distinct symbols and bind them explicitly when ambiguous:

```python
group, member = sb.item("group"), sb.item("member")
adjusted = f.groups.list.map(
    group.values.list.map(member + group.offset, item=member),
    item=group,
)
```

Unbound and shadowed item symbols fail before consuming rows. The old `_` token
belongs to `sbo.chain`, not list scope. `map`, `filter`, `flat_map`, `sort_by`,
`any`, `all`, and `count_where` also accept Python item callbacks. `reduce` takes
a Python `(accumulator, item)` callback and an optional initial value.

`unique` and set-like operations preserve first occurrence order and support
nested JSON values. `zip` stops at the shortest input. `get`, `first`, and `last`
have lazy defaults, defaulting to null. Empty `sum` is zero; empty `min`, `max`,
and `mean` are null. Null list members remain unless explicitly dropped; numeric
reductions over null members raise. Sorting follows Python ordering, including
its errors for incomparable values. `flatten(level=-1)` fully flattens.

## Objects and numbers

`.obj.get(key, default=None)` supports dynamic literal keys and a lazy default.
`keys`, `values`, `entries`, `pick`, `omit`, `merge`, and `rename` construct
objects. `merge(other, conflicts="right")` also accepts `left` or `raise`.
Renaming rejects duplicate output keys.

Numeric conveniences: `abs`, `round`, `floor`, `ceil`, `clip`, `sign`, `sqrt`,
`log(base=...)`, `exp`, `is_finite`, `is_nan`; unary `+`/`-`, `//`, `%`, `**`,
`abs(expr)`, and `round(expr, digits)` are supported. Domain errors are explicit.

## Selectors and global operations

`cs.names(...)`, `starts_with(...)`, `ends_with(...)`, `matches(regex)`, and
`all()` select **top-level keys present in each row**, with `|`, `&`, `-`, and
`~` for set composition. They perform no schema scan. Use them in `select`,
`transform_fields(selector, builder)`, `rename_fields(selector, name_builder)`,
`require_fields`, and `drop_nulls`. Selectors cannot require a name absent from
a row; pass an explicit path to `require_fields("required")` for that check.

DataTree terminals include `first(default=None)`, `one()` (reads at most two
rows), `is_empty()` (preserves bounded lookahead), `preview(n)`/`peek(n)`,
`to_columns()`, `iter_batches(size)`, and `count_rows()`. `first` consumes one
row on a single-pass tree. `to_columns` retains `MISSING` for absent fields.

`order_by(f.group.asc(), f.score.desc())` materializes the input. Existing
`group_by(key)` still returns rows containing `k` and `members`; it now supports
`.agg(total=sb.sum(f.amount), count=sb.count_rows())`. Aggregate factories also
include `mean`, `min`, `max`, and `collect_list`. Aggregation skips missing/null
values except `count_rows`, which counts every row. Ungrouped `.agg(...)`
reduces the entire finite tree. Group keys may be expressions, including
`sb.array(f.a, f.b)` for a compound key.

`unique_by(*keys)` retains a growing seen-key set; `value_counts(field)` groups
and counts; `top_k(k, by=expr, largest=True)` scans a finite source using O(k)
selection storage. `sb.concat(*trees)` concatenates in order. These global
operations belong on DataTree; Program remains a row-local transformation.
Neither grouping nor a top-k result can complete on an unbounded source.
