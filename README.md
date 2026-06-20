# SunBear — Invertible, Row-Based JSON Data Engine

SunBear is a **row-based** data processing library for tree-structured JSON
data. It builds **constructive invertibility** (L1/L2) into every operation:
every transform records a backward closure, so `invert_all()` can unwind the
full pipeline back to the source state.

## Key Features

- **Immutable, thread-safe DataTree** — every operation returns a new tree
- **Constructive invertibility** — `invert()` undoes the last op, `invert_all()`
  unwinds the entire pipeline
- **Declarative expression builder** (`dt.expr(...)`) — syntactic sugar that
  lowers to invertible DataTree ops:
  - `assign`, `keep` (row filter), `fork`/`case` (conditional branches)
  - `sbo` value-tier ops: `flatten`, `filter`, `map`, `reduce`, `chain`
  - `Expr.__call__` syntax: `b.createdAt(lambda t: datetime.fromisoformat(t))`
- **Schema inference and reconciliation** — type-level schema trees with null
  invariance, type invariance, and non-transitive semantics
- **Rich record indexer system** — dotted paths, tuples, lists, dicts
- **No external dependencies** (beyond Python 3.10+)

## Quick Start

```python
import sunbear as sb
from sunbear.expr import b, assign, keep, Symbols
import sunbear.ops as sbo
import numpy as np

records = [
    {"name": "Alice", "age": 30, "height": 170,
     "tags": [[["ring"], [40, 44]], [["red"], [31, 34]]]},
    {"name": "Bob",   "age": 25, "height": 165, "tags": []},
]

dt = sb.DataTree.from_records(records)

# Basic projection and aggregation
mu = np.mean(dt.pluck(b.age))
std = np.std(dt.pluck(b.age))

# Expression pipeline
dt2 = dt.expr(
    assign(b.s_age, (b.age - mu) / std),
    assign(b.flat_tags, sbo.chain(
        sbo.flatten(b.tags, -1),
        sbo.filter(_, lambda x: isinstance(x, str)),
    )),
    keep(sbo.length(b.flat_tags) > 0),
)

# Invertible — round-trip back to original
assert dt2.invert_all().twigs == dt.twigs
```

## Installation

```bash
pip install -e .   # editable install from source
```

Requires Python ≥ 3.10.

## Documentation

See [`notes_v3.md`](notes_v3.md) for full architecture docs, API reference,
and examples.

## Project Status

Version 0.2.0 — Active development. Milestones M0–M3 complete (expr builder
with assign, keep, fork/case fast path, sbo ops, chain/placeholder, callable
Expr). M4 (general path for fork/case with partition/recombine) deferred
pending ordering-tiebreak design.