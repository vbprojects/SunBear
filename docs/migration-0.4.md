# Migrating to 0.4

The root API is `import sunbear as sb; from sunbear import f`. `f` and the old
`b` are the same namespace. Use `sunbear.ops` for row statements,
`sunbear.selectors` for field selection, `sunbear.io` for file sources/sinks,
and `sunbear.cache` for explicit memoization.

Implementation modules are now `tree`, `program`, `record`, `schema`, and
`asyncio`. The old capitalized modules are compatibility shims; their public
classes have identical identity to the root and lowercase imports. Existing
explicit root imports remain available. Star imports now focus on the ordinary
public API; private helpers and compiler registries are no longer advertised.
No runtime dependency was added. Python 3.10 remains the minimum version.

## Behavior to review

- `select` is now atomic, including the old expression builder. All RHSs see
  the input, so swapping fields works. The builder still returns a list of
  statements for compatibility with `*select(...)`. `assign` remains sequential.
- Named projection fields and aliases are literal output keys. Positional nested
  paths retain the historical behavior of selecting their complete top-level
  object. Duplicate projected output keys now raise.
- New method/accessor names can collide with fields. Write `f["str"]`,
  `f["list"]`, `f["obj"]`, or `f["apply"]` to address such fields.
- New typed accessors propagate missing/null and reject wrong types. Low-level
  `sbo` helpers retain their historical coercion behavior.
- `DataTree.set(path, expression)` now evaluates expression values. Wrap an
  intended literal with `sb.lit(...)`; serialized outputs still require supported
  data types. Declarative edits preserve nested isolation.
- `group_by` still returns grouped DataTree rows with `k` and `members`; `.agg`
  adds named reductions. Global operations remain outside Program.
- `fill_missing` now evaluates its fallback lazily. Conditional values and the
  new `fill_null`/`coalesce` helpers also evaluate only needed branches.
- Expression normalization changed for new conveniences and atomic projection;
  memoization keys include those operations. Old computation entries need not be
  reused. File cache format and explicit output-persistence contracts remain.

Source lifetime, bounded peek/materialize, missing/null semantics, immutable
Programs, assertion behavior, and explicit caches from 0.3 remain in place.
See [the 0.3 migration guide](migration-0.3.md) for those earlier changes.

`emit` and `targets` generate output for external consumers. They do not store
records, open connections, or execute commands. Graph and logic namespaces are
experimental and expose narrower capabilities than full graph databases or
Datalog engines. See [output contracts](outputs.md) before integrating a target.
