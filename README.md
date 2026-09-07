# SunBear — Lazy, Schema-Aware JSON Data Engine

SunBear is a **row-based** data processing library for tree-structured JSON
data. It combines lazy evaluation, a declarative expression builder, row-based
caching, and type-level schema inference into a lightweight, composable toolkit.

## Key Features

- **Lazy DataTree** — iterator-native design; primitives (`map`, `filter`,
  `branch_map`) return generators that don't materialize until consumed
- **Plan layer** — inter-record operations (`group_by`, `join`, `reduce_by`)
  build an index with cardinality detection (1:1, 1:N, N:1, N:M)
- **Declarative expression builder** (`dt.expr(...)`) — syntactic sugar that
  lowers to DataTree ops:
  - `assign`, `keep` (row filter), `fork`/`case` (conditional branches)
  - `sbo` value-tier ops: `flatten`, `filter`, `map`, `reduce`, `chain`
  - `Expr.__call__` syntax: `b.createdAt(lambda t: datetime.fromisoformat(t))`
- **Row-based Program caching** — `Program` defers an expr pipeline; each
  input row is hashed individually for cache hit/miss
- **Schema inference and reconciliation** — type-level schema trees with null
  invariance, type invariance (Leaf equivalence), and non-transitive semantics
- **Rich Record indexer** — dotted paths, tuples, lists, dicts; single `_walk`
  for get/set/delete
- **Async data sources** — `ADict` bridges async streams (HTTP, WebSocket)
  into synchronous DataTrees
- **No external dependencies** (beyond Python 3.10+; NumPy optional for
  aggregations)

## Architecture Overview

| Module      | Purpose |
|-------------|---------|
| `DataTree`  | Lazy row-based table; primitives return generators, inter-record ops use Plan indexing |
| `Record`    | Row payload with a single recursive `_walk` for get/set/delete; mutable, shared by reference |
| `Plan`      | Index built from a materialized stream with cardinality detection |
| `Schema`    | Type-level schema trees with inference, reconciliation, and rich visualization |
| `Program`   | Deferred expr pipeline with row-based caching (FileCache backend) |
| `expr`      | Declarative expression builder (AST → per-row closures) |
| `sbo`       | Value-tier intra-record ops (flatten, filter, map, reduce, chain) |
| `ADict`     | Async dict proxy for bridging async data sources |

## Quick Start

```python
import sunbear as sb
from sunbear.expr import b, assign, keep, sbo

records = [
    {"name": "Alice", "age": 30, "tags": [["ring"], ["gold"]]},
    {"name": "Bob",   "age": 25, "tags": []},
    {"name": "Carol", "age": 17, "tags": [["silver"], ["bronze"]]},
]

dt = sb.DataTree.from_records(records)

# Expression pipeline
dt2 = dt.expr(
    assign(b.status, "active"),
    assign(b.flat_tags, sbo.flatten(b.tags, -1)),
    keep(b.age >= 18),
)

print(dt2.collect())
# [{'name': 'Alice', 'age': 30, 'tags': [...], 'status': 'active', 'flat_tags': ['ring', 'gold']},
#  {'name': 'Bob', 'age': 25, 'tags': [], 'status': 'active', 'flat_tags': []}]

# Program (deferred with caching)
from sunbear import Program

prog = Program(name="adults").expr(
    assign(b.status, "active"),
    keep(b.age >= 18),
)
result = prog(dt)   # first run: cache miss, executes pipeline
result = prog(dt)   # second run: cache hit, skips computation
```

## Installation

```bash
pip install -e .   # editable install from source
```

Requires Python ≥ 3.10.

## Component Docs

- **[DataTree](docs/datree.md)** — construction, lazy primitives, inter-record ops, terminal extractors
- **[Record](docs/record.md)** — payload structure, indexer resolution, get/set/delete/copy/move
- **[Schema](docs/schema.md)** — type hierarchy, node tree, inference, reconciliation, visualization
- **[Program](docs/program.md)** — deferred pipelines, row-based caching, FileCache, to_DataTree
- **[Expr](docs/expr.md)** — expression AST, statement builders, sbo ops, chain/placeholder

## Project Status

Version 0.2.0 — Active development. Core modules complete with 140+ tests.
