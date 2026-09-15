"""Dependency-free output dialects. These compile payloads; callers execute them."""

from .sql import SQL
from .documents import JSONL, Elasticsearch, MongoDB, Kusto
from .rdf import RDF
from .datalog import Datalog
from ..emit import Target, Batch, Artifact


def sql(dialect="postgresql", *, output="script", parameter_style=None):
    return SQL(dialect, output=output, parameter_style=parameter_style)


def jsonl():
    return JSONL()


def elasticsearch():
    return Elasticsearch()


def mongodb():
    return MongoDB()


def kusto(*, schema, mapping="sunbear"):
    return Kusto(schema=schema, mapping=mapping)


def rdf(format="ntriples"):
    return RDF(format)


def datalog(dialect="souffle", *, output="files"):
    return Datalog(dialect, output=output)


__all__ = [
    "sql",
    "jsonl",
    "elasticsearch",
    "mongodb",
    "kusto",
    "rdf",
    "datalog",
    "Target",
    "Batch",
    "Artifact",
]
