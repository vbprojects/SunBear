# Output compilers

SunBear transforms incoming records locally, evaluates typed write declarations,
and serializes backend-readable output. It has no drivers, connections, database
execution, graph query engine, or external runtime dependencies. SQL expressions
are not a translation of arbitrary Python code: row transformations run in
SunBear before values are serialized.

## Compile, then stream

```python
import sunbear as sb
from sunbear import f, emit, targets

transform = sb.Program().where(f.id.is_not_null()).select(id=f.id, text=f.text.fill_missing(None))
job = transform.emit(emit.row("posts", key="id", mode="upsert")).compile(
    targets.sql("postgresql", output="script")
)
for batch in job.stream([{"id": "p1", "text": "hello"}], batch_rows=500, batch_bytes=1_048_576):
    assert batch.text.startswith('INSERT INTO "posts"')
```

A bound tree can also call `.emit(...).compile(...).stream()` without another
source. `Program.emit(...)` requires a source for each run. Multiple declarations
execute in declaration order for each row. Target/type/operation incompatibility
is rejected during compilation; data-dependent errors report the row and
output destination. Unsupported values raise, never stringify implicitly.

`Batch` exposes `text`, `payload`, `statements` (SQL text/parameter tuples),
`destination`, `content_type`, `operation_count`, `byte_size`, and optional
`source_tokens`. Use the field appropriate to the target. Setup is returned
separately by `job.artifacts()` as named text artifacts. No setup is executed.

`batch_rows` limits **logical output operations**, not input rows: one input can
produce several triples or writes. Batches also cap serialized UTF-8 bytes,
including JSON-serialized SQL parameters; source metadata is excluded. MongoDB's
bound measures JSON command bytes, not the backend's BSON size. A single
oversized operation raises. The accumulator reads at most one operation ahead
of a returned batch, uses conservative per-operation sizing, and never splits
an Elasticsearch action from its document. Backend request limits still belong
to the caller's transport configuration.

A source row or list can itself be arbitrarily large; bounded output batching
does not make an arbitrarily large input record bounded. Filters may scan many
input rows before producing the next output. Prior yielded batches remain valid
if a later row fails; an unfinished batch is discarded on failure. SunBear
preserves order and duplicates in generated output; a target database may have
set semantics, conflict rules, or reorder application work.

`source_token=lambda meta: meta["i"]` copies source metadata alongside each emitted
operation. Tokens can repeat when one input expands into several operations.
They are diagnostic information, not safe commit offsets: a source row can
span batches and a filtered row can produce no output. Acknowledgement,
checkpointing, transaction boundaries, retries, and idempotency are application
responsibilities. Generating an upsert does not imply exactly-once delivery.

## Async sources

```python
from contextlib import aclosing

async def consume(source, send):
    async with aclosing(job.astream(source, batch_rows=500)) as batches:
        async for batch in batches:
            await send(batch.text)
```

`astream` accepts an async iterable of dictionaries on a Program-backed job.
It reuses the compiled row executor, honors an explicit computation cache,
flushes the cache on exit, and closes the source on completion/cancellation or
explicit `aclose()` by default. Use `close_source=False` to retain source
ownership. Use `aclosing` if breaking out of the loop early. There are no hidden
background tasks or unbounded queues. A partially filled batch is emitted on
normal exhaustion; an error/cancellation discards it. Sync single-pass trees
retain their established source lifetime behavior; closing an output generator
does not promise to close an external source owned by the caller.

## Relational SQL

`emit.row(table, key=(...), mode="insert"/"upsert"/"delete", schema=..., **fields)`
uses the transformed row or explicitly named field expressions. Tables and
columns are literal identifiers and are quoted; a dot in a table name is part
of that name, not a schema separator. Values are separately bound or safely
escaped for the selected dialect.

Provide `schema={"id": "integer", "body": "text", "metadata": "json"}` to
validate types and generate a separate `CREATE TABLE IF NOT EXISTS` artifact.
Types are `text`, `integer`, `real`, `boolean`, `json`. A key in setup becomes a
non-null primary key. Without a declared schema, the **first row's column names**
freeze for that table and stream; SunBear does not infer column types or emit
DDL. Later rows must have exactly the same columns. A new stream starts a new
schema session. Use `select` and explicit defaults to normalize heterogeneous
records. There is no automatic schema evolution or inspection of existing tables.
Existing database constraints remain authoritative.

Upsert/delete require non-null keys. Upsert uses `ON CONFLICT (...) DO UPDATE`,
or `DO NOTHING` when all columns are keys. Delete uses equality predicates for
the declared key columns. PostgreSQL and SQLite need corresponding unique/primary
key constraints. Integers are bounded to signed 64-bit values; nested values
require a declared `json` column. `None` maps to SQL NULL. SQLite stores JSON as
text; PostgreSQL uses JSONB. NUL in ordinary SQL text is rejected for portability.

`output="script"` returns executable SQL text. `output="parameters"` returns a
sequence of independent `(sql, parameters)` statements; execute each pair with
the matching client. PostgreSQL defaults to `$1` numeric parameters; select
`parameter_style="format"` for `%s` clients. SQLite uses `?` (`qmark`). Parameter
numbering restarts for each statement. Do not concatenate parameter tuples and
execute the entire batch as one parameterized statement. JSON parameters are
encoded strings. PostgreSQL scripts use explicit `E'...'` literals so escaping
does not depend on session string settings.

## Documents

`emit.document(collection, key=f.id, mode=..., value=expression)` uses the
transformed row by default. `value=sb.object(...)` provides a custom body. IDs
are strings or integers; replacement/update/deletion require a non-null key.
No implicit BSON/Extended JSON coercion is performed.

| Target | Insert | Replace | Update | Delete |
|---|---|---|---|---|
| JSONL | Record line | Unsupported | Unsupported | Unsupported |
| Elasticsearch | `create` action | `index` action | `update` with `doc` | `delete` action |
| MongoDB | `insert` command | `update` with replacement and upsert | `$set`, no upsert | Single-document `delete` |
| Kusto | JSON ingestion record | Unsupported | Unsupported | Unsupported |

Elasticsearch emits bulk NDJSON with a final newline and keeps each action/body
pair together. IDs are converted to Elasticsearch string IDs; choose one native
ID type in your mapping if `1` and `"1"` must be distinct. MongoDB emits native
collection command **payload dictionaries** with `ordered: true`, splitting
batches at command boundaries. Send `batch.payload` using your own command API.
Declared keys use `_id`; conflicts with a body `_id` raise. MongoDB updates reject
top-level names containing `.` or starting with `$`; replacement documents reject
operator-like top-level keys. JSONL supports append-only rows/documents; it is
not a generic mutation protocol.

Kusto requires `targets.kusto(schema={...}, mapping="sunbear")`. It produces JSON
lines plus separate `.create table` and JSON ingestion mapping artifacts.
Select that mapping in the application's ingestion request. It emits no
`.ingest inline` commands. Types include `string`, `long`, `real`, `bool`,
`datetime`, `dynamic`, `guid`, and `timespan`; names use simple identifiers.
The compiler checks JSON value kinds; Kusto validates lexical datetime/GUID/
timespan formats. This target represents Kusto specifically, not a common query
language shared by document databases.

## Graph/RDF (experimental)

```python
from sunbear import graph as g

post = g.ref("post", f.id)
social = (
    g.Mapping("https://example.org/social/")
    .node(post, kind="Post", text=f.text)
    .edge(post, "authored_by", g.ref("user", f.author))
    .edges(post, "mentions", g.ref("post", f.mentions))
)
job = social.compile(targets.rdf("ntriples"))
```

`g.ref(kind, expression)` maps string/integer IDs to absolute IRIs under the
mapping namespace. Both kind and ID are percent-encoded; an `s/` or `i/` segment
distinguishes string and integer identities. `.node` emits type and property
triples; `.edge` emits one relationship; `.edges` expands a list of target IDs.
`.triple(subject, predicate, object, when=..., graph=..., action=...)` is the
low-level form. `g.iri(...)` explicitly identifies a resource, and
`g.literal(value, datatype=.../language=...)` creates a typed or language-tagged
literal. Arbitrary nested values require explicit mapping into further nodes,
relationships, or fact fields.

`when` guards a declaration before references are evaluated. A missing/null
property is omitted by default; `Mapping(..., nulls="raise")` rejects it. Missing
or null entity IDs always raise when evaluated; guard optional relationships.
Missing/null relationship lists may be omitted, but each present list member
must be a valid ID. References do not fetch data or require an earlier node
statement. The same declaration can therefore link a post to an unseen post.

`relationship(identity, subject, predicate, object, **properties)` emits an RDF
Statement reification with your relationship identity and properties. Pass
`assert_edge=True` to also assert the underlying edge. Reification alone does
not assert that edge. `mapping.then(other)` concatenates mappings sharing a
namespace. `mapping.emit(tree_or_program)` composes with a transformation.

N-Triples supports assertions in the default graph; N-Quads adds named graphs.
`targets.rdf("sparql")` emits ordered `INSERT DATA`/`DELETE DATA` updates and
supports `action="retract"`. Assertion files cannot encode retractions. There
is no implicit replacement of every property of a resource; declare exact
triples to retract, or use a backend-specific extension. Strings are escaped;
absolute IRIs, datatype IRIs, and language tags are validated.

## Datalog (experimental)

```python
from sunbear import logic as l

edge = l.relation("edge", source="symbol", target="symbol")
reach = l.relation("reach", source="symbol", target="symbol")
x, y, z = l.var("X"), l.var("Y"), l.var("Z")

logic = (
    l.Program()
    .facts(edge(f.id, f.reply), when=f.reply.is_not_null())
    .rule(reach(x, y), edge(x, y))
    .rule(reach(x, z), reach(x, y), edge(y, z))
    .output(reach)
)
job = logic.compile(targets.datalog("souffle"))
setup = job.artifacts()  # program.dl: .decl, .input, positive rules, .output
batches = job.stream([{"id": "p1", "reply": "p2"}])  # destination: edge.facts
```

Write each batch to its `destination`, preserving order within a fact file.
Create empty input files for declared input relations that emitted no facts.
Run Souffle yourself after producing the files. `output="inline"` emits facts
as Datalog source in `facts.dl`; append them to the program artifact before
running, and no `.input` directives are emitted.

This dialect supports named, typed, n-ary relations, facts, positive Horn rules,
and output declarations. Head variables must be bound in the body; arity,
conflicting declarations, and variable type consistency are checked before
consumption. Types are `symbol`, `number`, `unsigned`, and `float`; integer
values use the conservative default 32-bit domain. Null has no implicit fact
encoding. Default fact files use Souffle's raw TSV format; control characters
in symbols are rejected instead of corrupting rows. Inline strings are quoted
and escaped, also rejecting controls. Negation, aggregates inside logic rules,
engine execution, and continuous incremental rule evaluation are not provided.
Datalog facts remain n-ary facts rather than being forced into RDF triples.

## Extending targets and checking dialects

Implement the structural `emit.Target` protocol: `validate(declarations)`,
`session()`, `encode(operations) -> Batch`, and `artifacts(declarations)`.
Validation is static; return a fresh session for mutable schema state.
Optionally implement `batch_key(operation)` to split batches at additional
boundaries. Encoding a combined batch must not use more bytes than the sum of
individually encoded operations. Output declarations implement `evaluator()`,
returning a compiled record-to-operations iterator. The exported typed write
objects are `emit.RowWrite`, `emit.DocumentWrite`, `graph.Triple`, and
`logic.Fact`. Custom declarations/targets should validate their own capabilities.

The default suite executes SQLite scripts and bound statements, checks wire
payloads, guards source consumption, and verifies RDF/Datalog examples. Optional
RDFLib tests independently parse N-Triples, N-Quads, and SPARQL output. PostgreSQL,
MongoDB, Elasticsearch, Kusto, and Souffle server/engine execution are not part
of the offline test suite.

Dialect references: [PostgreSQL INSERT](https://www.postgresql.org/docs/current/sql-insert.html),
[SQLite UPSERT](https://www.sqlite.org/lang_upsert.html),
[Elasticsearch bulk](https://www.elastic.co/docs/api/doc/elasticsearch/operation/operation-bulk),
[MongoDB update commands](https://www.mongodb.com/docs/manual/reference/command/update/),
[Kusto JSON mapping](https://learn.microsoft.com/en-us/kusto/management/json-mapping),
[W3C N-Triples](https://www.w3.org/TR/n-triples/),
[SPARQL Update](https://www.w3.org/TR/sparql11-update/),
[Souffle tutorial](https://souffle-lang.github.io/tutorial).
