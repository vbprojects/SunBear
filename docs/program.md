# Programs, caches, and saved runs

A Program is an immutable, compiled row-local transformation. Creating or
extending one validates every statement, including unselected conditional
branches, before consuming data. All currently supported statements are
row-local (including row filtering). Global and expanding statement kinds are
rejected; use explicit DataTree global operations outside a Program.

```python
from sunbear import DataTree, Program, FileCache, write_jsonl, read_jsonl
from sunbear.expr import b, assign, keep

base = Program(name="adults").expr(keep(b.age >= 18))
labeled = base.expr(assign(status="active"))  # base remains unchanged
rows = DataTree.from_records([{"age": 30}, {"age": 17}])
assert labeled(rows).collect() == [{"age": 30, "status": "active"}]
```

Execution preserves source replayability and uses the same compiled executor
as DataTree.expr(). Statements inside fork/case have the same semantics as
top-level statements; keep(False) filters the row from the whole program.
TransformationError carries step, row, operation, and a target path where
available. The original exception remains available as __cause__. Nested
errors refer to the step within their block. Input records are not printed.

Programs own a copy of their expressions and literals. Python callbacks remain
external code: callers must keep them pure if they want deterministic replay.
Declarative writes copy modified ancestors. Untouched branches can remain
shared. Direct Record access and arbitrary callbacks are explicit mutable
interfaces; use materialize() when a fully isolated output snapshot is needed.

## Explicit caching

```python
cached = Program(cache=FileCache("adults")).expr(keep(b.age >= 18))
assert cached(rows).collect() == [{"age": 30}]
```

A display name does not configure caching or determine computation identity.
Keys include a format version, normalized operations, parameters, and input
data. Extending a program produces a different namespace, even when both use
the same FileCache. Cache hits still preserve each input occurrence.

Callbacks require cache_version:

```python
from sunbear.expr import sbo
cached = Program(cache=FileCache("tags"), cache_version="normalize-v1").expr(
    assign(tags=sbo.map(b.tags, str.lower))
)
```

cache_version is a caller-maintained identifier for callback implementations
and every external/captured dependency. Change it whenever any dependency
changes. It is not an automatic code fingerprint. Cache only deterministic
row-local computations. Metadata and callback side effects are not memoized;
cache records represent output data, not an execution log.

The codec accepts JSON objects with string keys, lists, strings, finite
floats, integers, booleans, and null. Tuples, dates, custom objects, missing
markers, non-string keys, and non-finite floats raise instead of becoming
strings. Convert them explicitly before caching or saving.

FileCache batches writes (flush_every=100 by default), flushes on completed
execution or generator cleanup, and supports explicit flush(). It atomically
replaces its JSON file. A suspended iterator may still have pending entries;
call cache.flush() when durable persistence is required before completion.
Each file supports one writer. Old cache formats are rejected; use a new
filename or remove the obsolete cache.

## Save an execution

```python
write_jsonl(labeled(rows), "adults.jsonl")
saved = read_jsonl("adults.jsonl")
assert saved.collect() == labeled(rows).collect()
```

write_jsonl consumes finite output incrementally into a temporary file and
publishes the destination atomically only after success. Order and duplicates
are preserved. A failed transformation or serialization leaves an existing
destination intact. read_jsonl reopens the file on each traversal.

to_DataTree() remains deprecated for cache inspection. Its entries are unique
memoized inputs accumulated across runs and namespaces, not the ordered output
of the latest execution. It emits a warning; migrate saved-output workflows to
write_jsonl/read_jsonl.
