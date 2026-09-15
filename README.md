# SunBear

Declarative pipelines for nested records, streams, and database-ready output.
Python 3.10+, with **no external runtime dependencies**.

Explore a bounded sample, build a reusable transformation, then stream rows,
SQL, documents, RDF triples, or Datalog facts to your own consumer.

## Start with ordinary Python data

```python
import sunbear as sb
from sunbear import f

records = [
    {"id": "p1", "author": {"id": "u1"}, "text": " Hello! ", "tags": ["python", "python"]},
    {"id": "p2", "author": {"id": "u2"}, "text": "Nested data", "tags": []},
]

posts = (
    sb.Program(name="posts")
    .where(f.text.is_not_null())
    .select(id=f.id, author_id=f.author.id, text=f.text.str.strip(), tags=f.tags)
    .assign(tags=f.tags.list.unique())
    .assign(tag_count=f.tags.list.len())
)

rows = sb.DataTree.from_records(records).pipe(posts)
assert rows.peek(1)[0]["text"] == "Hello!"  # bounded, preserves the next row
assert rows.collect() == [
    {"id": "p1", "author_id": "u1", "text": "Hello!", "tags": ["python"], "tag_count": 1},
    {"id": "p2", "author_id": "u2", "text": "Nested data", "tags": [], "tag_count": 0},
]
assert rows.count_rows() == 2  # replayable input stays replayable
```

Use `DataTree.from_iter(events)` for a single-pass source,
`sb.io.read_jsonl(path)` or `sb.io.read_csv(path)` for replayable files.
CSV values are strings until you explicitly cast them.
`materialize()` saves a finite stream in memory; `write_jsonl(path)` saves an
ordered, duplicate-preserving run. Caching is a separate, explicit choice.

## Compile a stream for a database

```python
from sunbear import emit, targets

job = posts.emit(
    emit.row(
        "posts", key="id", mode="upsert",
        schema={"id": "text", "author_id": "text", "text": "text", "tags": "json", "tag_count": "integer"},
    )
).compile(targets.sql("sqlite", output="parameters"))

# Setup is separate from data. Your application decides when to execute it.
setup = job.artifacts()
batches = list(job.stream(records, batch_rows=100, batch_bytes=1_048_576))
assert batches[0].operation_count == 2
assert batches[0].statements[0][1][0] == "p1"
# for sql, parameters in batch.statements: connection.execute(sql, parameters)
```

SunBear generates code and payloads. It opens no database connections and
makes no acknowledgement, transaction, or exactly-once guarantees. `stream()`
is incremental; `astream()` uses the same compiled transformation with an async
source. The caller sends each batch and handles retries and commits.

| Target | Output |
|---|---|
| `targets.sql("postgresql" / "sqlite")` | SQL scripts or statements with separate parameters; insert, upsert, delete |
| `targets.jsonl()` | Append-only JSON records |
| `targets.elasticsearch()` | Bulk action/document NDJSON with the required final newline |
| `targets.mongodb()` | Collection insert, update, replacement, and delete command payloads |
| `targets.kusto(schema=...)` | JSON ingestion data plus table/mapping KQL artifacts |
| `targets.rdf("ntriples" / "nquads" / "sparql")` | RDF statements or SPARQL DATA updates |
| `targets.datalog("souffle")` | Typed relation/rule program and streamed fact files |

These are declared dialects with explicit capabilities. KQL is specific to
Kusto; document stores use their own ingestion formats.

## Map posts to relationships

```python
from sunbear import graph as g

post = g.ref("post", f.id)
author = g.ref("user", f.author.id)
social = (
    g.Mapping(namespace="https://example.org/social/")
    .node(post, kind="Post", text=f.text)
    .edge(post, "authored_by", author)
    .edge(post, "replies_to", g.ref("post", f.reply), when=f.reply.is_not_null())
)

triples = "".join(batch.text for batch in social.compile(targets.rdf()).stream(records))
assert "authored_by" in triples
```

`sunbear.graph` and `sunbear.logic` are experimental. Graph references generate
stable absolute IRIs; references can point at entities absent from the current
stream. Relationships with properties use an explicit relationship identity.
There is no hidden graph store or automatic relationship discovery.

## Public namespaces

| Namespace | Purpose |
|---|---|
| `sunbear` | `DataTree`, `Program`, `f`, literals, constructors, aggregations |
| `sunbear.expr` | Value expressions and advanced composition |
| `sunbear.ops` | Declarative statement builders |
| `sunbear.selectors` | Composable field selectors |
| `sunbear.io` | CSV/JSONL sources, JSONL persistence, async adapters |
| `sunbear.cache`, `sunbear.schema` | Explicit memoization and schema tools |
| `sunbear.emit`, `sunbear.targets` | Typed writes and output compilers |
| `sunbear.graph`, `sunbear.logic` | Experimental graph and Datalog declarations |

Implementation modules use lowercase names. Old imports such as
`from sunbear.DataTree import DataTree` remain compatible; `b` aliases `f`.

## Install and learn more

```sh
pip install -e .
PYTHONPATH=src python -m unittest discover -s tests
```

- [Fluent API and syntax reference](docs/syntax.md)
- [Output targets, streaming contracts, and dialect examples](docs/outputs.md)
- [0.4 migration guide](docs/migration-0.4.md)
- [Runnable offline social pipeline](examples/social_outputs.py)
- Advanced internals: [DataTree](docs/datree.md), [Record](docs/record.md),
  [Schema](docs/schema.md), [Program](docs/program.md), [legacy expression API](docs/expr.md)

Version 0.4.0. Graph and logic APIs are experimental; output capabilities and
serialization limits are documented per target.
