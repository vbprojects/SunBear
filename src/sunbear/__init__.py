"""Composable nested-data transformations and dependency-free output compilers."""

from importlib import import_module as _import_module

# Preload compatibility modules before binding root classes. Later legacy
# imports then cannot replace sb.Program or sb.DataTree with module objects.
for _legacy in ("DataTree", "Program", "Record", "Schema", "ADict"):
    _import_module("." + _legacy, __name__)

from .tree import DataTree, Plan, Twig, SchemaSample
from .program import Program
from .cache import AbstractCache, FileCache
from .record import Record, _freeze, _mkpath
from .asyncio import ADict, ADictStream
from .schema import (
    Schema,
    SchemaType,
    Primitive,
    NullType,
    UnionType,
    ListType,
    CustomType,
    Leaf,
    Branch,
    Node,
    infer_schema,
    reconcile,
    combine_types,
)
from .paths import MISSING, PathSpec, Key, Index, Traverse
from .expr.lower import TransformationError
from .expr.ast import b as f
from .expr._sugar import (
    lit,
    field,
    item,
    all_of,
    any_of,
    not_,
    object_ as object,
    array,
    concat_str,
    format_str,
    when,
    match,
    coalesce,
)
from ._table import (
    count_rows,
    sum_ as sum,
    mean,
    min_ as min,
    max_ as max,
    collect_list,
    concat,
)
from .io import read_csv, read_jsonl, write_jsonl
from . import expr, ops, selectors, io, cache, schema, emit, targets, graph, logic

b = f

# Advanced historical names above remain explicitly importable; the advertised
# namespace focuses on ordinary row workflows.
__all__ = [
    "DataTree",
    "Program",
    "Record",
    "Schema",
    "MISSING",
    "TransformationError",
    "f",
    "b",
    "lit",
    "field",
    "item",
    "all_of",
    "any_of",
    "not_",
    "object",
    "array",
    "concat_str",
    "format_str",
    "when",
    "match",
    "coalesce",
    "count_rows",
    "sum",
    "mean",
    "min",
    "max",
    "collect_list",
    "concat",
    "read_jsonl",
    "write_jsonl",
    "read_csv",
    "expr",
    "ops",
    "selectors",
    "io",
    "cache",
    "schema",
    "emit",
    "targets",
    "graph",
    "logic",
]
