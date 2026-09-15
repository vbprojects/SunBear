# Migration to 0.3

- Replace filtering assert_(predicate) with keep(predicate). Assertions raise.
- Use infer_schema(sample=n).schema instead of implicit schema scans.
- Use peek(n) for retained inspection and materialize() for a reusable snapshot.
- Replace expression field != None with field.is_not_null() when missing fields
  must also be excluded. exists() includes explicit null.
- Path.indexer now carries a PathSpec rather than a dotted string. Pass paths
  directly to Record/DataTree APIs instead of splitting indexer strings.
- Bracket strings are literal keys; integer brackets are real array indices.
- Null-valued move/copy operations now preserve the destination null.
- add() fills missing fields only. default() still fills missing or null.
- Save the returned definition when extending: program = program.expr(...).
- Names are display labels. Configure cache=FileCache(...) explicitly.
- Version cached callbacks with cache_version, including captured dependencies.
- Old cache files are incompatible; choose fresh filenames.
- Save ordered output using write_jsonl(), not Program.to_DataTree().
- Cached/saved values must be strict JSON; convert dates and custom objects
  explicitly. No default=str serialization remains.
- Runtime pipeline errors are TransformationError (a ValueError subclass),
  with the original exception in __cause__.
