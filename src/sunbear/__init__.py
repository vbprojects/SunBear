"""sunbear — minimal, iterator-native row-based JSON data engine.

Architecture:
    - DataTree: lazy inter-record table; primitives return iterators
    - Plan:     explicit index with cardinality detection for group_by/join
    - Record:   single _walk for get/set/delete; mutable, shared by ref
    - Schema:   carried over from v3; type-level trees with Jupyter viz
    - expr:     declarative builder, AST compiles to per-row closure

Dropped: invertibility (no _history, no undo closures, no provenance markers).
"""
from .ADict import ADict, ADictStream
from .DataTree import DataTree, Plan, Twig, SchemaSample
from .Program import Program, AbstractCache, FileCache
from .Record import Record, _freeze, _mkpath

from .Schema import (
    Schema, SchemaType, Primitive, NullType, UnionType, ListType, CustomType,
    Leaf, Branch, Node, infer_schema, reconcile, combine_types,
)

from . import expr

__all__ = [
    "ADict", "ADictStream",
    "DataTree", "Plan", "Twig", "SchemaSample",
    "Program", "AbstractCache", "FileCache",
    "Record", "_freeze", "_mkpath",
    "Schema", "SchemaType", "Primitive", "NullType", "UnionType",
    "ListType", "CustomType", "Leaf", "Branch", "Node",
    "infer_schema", "reconcile", "combine_types",
    "expr",
]

from .paths import MISSING, PathSpec, Key, Index, Traverse
from .sinks import write_jsonl, read_jsonl
from .expr.lower import TransformationError
__all__ += ["MISSING", "PathSpec", "Key", "Index", "Traverse", "write_jsonl", "read_jsonl", "TransformationError"]
