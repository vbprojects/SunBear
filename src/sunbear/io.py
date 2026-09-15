"""Dependency-free, replayable text inputs and explicit output persistence."""

from .sinks import read_jsonl, write_jsonl
from .asyncio import ADict, ADictStream


def read_csv(path, *, encoding="utf-8", **options):
    """Read CSV records as strings; cast fields explicitly in the pipeline."""
    import csv
    from .tree import DataTree

    def rows():
        with open(path, newline="", encoding=encoding) as source:
            yield from csv.DictReader(source, **options)

    return DataTree.from_iter_factory(rows)
