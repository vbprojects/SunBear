"""Declarative row statement builders; use Program methods for common pipelines."""

from .expr.lower import (
    assign,
    keep,
    filter_field,
    map_field,
    flatten,
    fork,
    case,
    select,
    rename,
    drop,
    copy_field,
    default,
    nest,
    unnest,
    assert_,
    mask,
    cast,
    upper,
    lower_str,
    trim,
    round_field,
    coalesce,
)
from .expr._sugar import all_of, any_of


def where(*predicates):
    return keep(all_of(*predicates))


def where_any(*predicates):
    return keep(any_of(*predicates))


def reject(*predicates):
    return keep(~all_of(*predicates))


require = assert_
