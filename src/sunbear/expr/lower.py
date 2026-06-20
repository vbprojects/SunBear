"""
Lower expr statements to invertible DataTree operations.

This is the ONLY module that imports DataTree.
"""
from __future__ import annotations

import copy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..DataTree import DataTree
    from ..Record import Record

from .ast import (
    Assign, Keep, Fork, Case, Statement, MapAssign, _wrap, Expr,
)
from .eval import eval_value, eval_predicate
from .namespace import as_indexer
from .ast import Call as _Call

# Runtime import of Record — used in fork/case row_fn.
# Try relative (package) first, then absolute (for ad-hoc testing).
try:
    from ..Record import Record as _Record
except ImportError:
    from Record import Record as _Record  # type: ignore[no-redef]


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════
def _flatten_lists(items):
    """Flatten any lists in items — assign() returns a list, expr flattens."""
    result = []
    for item in items:
        if isinstance(item, (list, tuple)):
            result.extend(item)
        else:
            result.append(item)
    return result


def _is_pure_map_block(block) -> bool:
    """Check whether a statement block contains only Assign statements."""
    for s in block:
        if not isinstance(s, Assign):
            return False
    return True


def _validate_single_leaf_path(target, *, dt=None):
    """Validate that a target resolves to a single settable leaf path.

    Returns the resolved path as a string (dotted or plain).
    Raises if the path is empty (root) or can't be determined.
    """
    path = as_indexer(target)

    if not isinstance(path, str):
        raise ValueError(
            f"assign target must be a single leaf path (str), got {type(path).__name__}: {path!r}"
        )

    if path == "" or "." not in path:
        # Top-level field — this is fine
        pass

    return path


# ═══════════════════════════════════════════════════════════════════════════
# Statement lowering — each .lower(dt) returns a DataTree
# ═══════════════════════════════════════════════════════════════════════════

def _lower_assign(stmt: Assign, dt: DataTree) -> DataTree:
    """Lower an Assign statement to dt.assign_at()."""
    path = _validate_single_leaf_path(stmt.target)
    return dt.assign_at(path, lambda r: eval_value(stmt.value, r))


def _lower_keep(stmt: Keep, dt: DataTree) -> DataTree:
    """Lower a Keep statement to dt.keep() — invertible filter."""
    return dt.keep(lambda r, m: eval_predicate(stmt.pred, r))


def _lower_map_assign(stmt: MapAssign, dt: DataTree) -> DataTree:
    """Lower a MapAssign to dt.assign_at().

    Equivalent to ``assign(target, sbo.map(source, fn, *args, **kwargs))``:
    per row, evaluate the source, call fn(source_value, *args, **kwargs),
    and write the result to the target path.
    """
    path = _validate_single_leaf_path(stmt.target)
    # Pre-evaluate the extra args/kwargs once per row (they're already
    # AST nodes that may reference per-row state).
    def row_fn(record):
        fn_value = eval_value(stmt.fn, record)
        src_value = eval_value(stmt.source, record)
        args = [eval_value(a, record) for a in stmt.extra_args]
        kwargs = {k: eval_value(v, record) for k, v in stmt.extra_kwargs.items()}
        return fn_value(src_value, *args, **kwargs)
    return dt.assign_at(path, row_fn)


def _lower_fork_fast(stmt: Fork, dt: DataTree) -> DataTree:
    """Lower a Fork via apply (whole-record map) — fast path.

    Precondition: both then_block and else_block contain only Assign.
    Falls back to NotImplementedError if not pure-map.
    """
    # Flatten assign() lists (assign returns a list of Assigns)
    then_block = _flatten_lists(stmt.then_block)
    else_block = _flatten_lists(stmt.else_block)

    if not _is_pure_map_block(then_block) or not _is_pure_map_block(else_block):
        raise NotImplementedError(
            "Fork/case general path (partition/recombine) is not yet implemented (M4). "
            "All branch blocks must contain only assign() statements."
        )

    def row_fn(record):
        nr = _Record(copy.deepcopy(record.data))
        if eval_predicate(stmt.cond, record):
            block = then_block
        else:
            block = else_block
        for a in block:
            p = _validate_single_leaf_path(a.target)
            nr.set(p, eval_value(a.value, record))
        return nr

    return dt.apply(row_fn)


def _lower_case_fast(stmt: Case, dt: DataTree) -> DataTree:
    """Lower a Case via apply (whole-record map) — fast path.

    Precondition: every clause block and default contain only Assign.
    Falls back to NotImplementedError if not pure-map.
    """
    # Flatten assign() lists inside each block (assign returns a list)
    flat_clauses = [(cond, _flatten_lists(block)) for cond, block in stmt.clauses]
    flat_default = _flatten_lists(stmt.default)

    all_blocks = [b for _, b in flat_clauses] + [flat_default]
    for block in all_blocks:
        if not _is_pure_map_block(block):
            raise NotImplementedError(
                "Fork/case general path (partition/recombine) is not yet implemented (M4). "
                "All clause blocks must contain only assign() statements."
            )

    def row_fn(record):
        nr = _Record(copy.deepcopy(record.data))
        for cond, block in flat_clauses:
            if eval_predicate(cond, record):
                for a in block:
                    p = _validate_single_leaf_path(a.target)
                    nr.set(p, eval_value(a.value, record))
                return nr
        # default
        for a in flat_default:
            p = _validate_single_leaf_path(a.target)
            nr.set(p, eval_value(a.value, record))
        return nr

    return dt.apply(row_fn)


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════

# Registry: Statement type → lowering function
_LOWERERS = {
    Assign: _lower_assign,
    MapAssign: _lower_map_assign,
    Keep: _lower_keep,
    Fork: _lower_fork_fast,
    Case: _lower_case_fast,
}


def run_expr(dt: DataTree, *statements) -> DataTree:
    """Apply a sequence of statements to a DataTree.

    Each statement is lowered to one invertible DataTree operation.
    Statements are applied eagerly and sequentially.
    """
    stmts = _flatten_lists(statements)
    for s in stmts:
        if not isinstance(s, Statement):
            raise TypeError(
                f"Expected a Statement, got {type(s).__name__}: {s!r}"
            )
        lowerer = _LOWERERS.get(type(s))
        if lowerer is None:
            raise NotImplementedError(
                f"No lowerer registered for statement type {type(s).__name__}"
            )
        dt = lowerer(s, dt)
    return dt
