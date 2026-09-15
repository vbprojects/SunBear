"""RDF 1.1 N-Triples/N-Quads and SPARQL 1.1 DATA update serialization."""

import math
from ._base import BaseTarget, Batch
from ..graph import TripleDeclaration, IRI, Literal

XSD = "http://www.w3.org/2001/XMLSchema#"


def _quoted(value):
    result = []
    for char in value:
        code = ord(char)
        if 0xD800 <= code <= 0xDFFF:
            raise ValueError("RDF text cannot contain unpaired surrogates")
        if char in "\t\b\n\r\f":
            result.append(
                {"\t": r"\t", "\b": r"\b", "\n": r"\n", "\r": r"\r", "\f": r"\f"}[char]
            )
        elif char == '"':
            result.append('\\"')
        elif char == "\\":
            result.append("\\\\")
        elif code < 32 or code == 127:
            result.append(f"\\u{code:04X}")
        else:
            result.append(char)
    return '"' + "".join(result) + '"'


def term(value):
    if isinstance(value, IRI):
        return "<" + value.value + ">"
    if not isinstance(value, Literal):
        raise TypeError("Expected typed RDF term")
    raw, datatype = value.value, value.datatype
    if datatype or value.language:
        if not isinstance(raw, str):
            raise TypeError(
                "Explicit RDF datatype/language requires a lexical string value"
            )
    elif type(raw) is bool:
        raw, datatype = ("true" if raw else "false"), XSD + "boolean"
    elif type(raw) is int:
        raw, datatype = str(raw), XSD + "integer"
    elif type(raw) is float:
        if not math.isfinite(raw):
            raise ValueError(
                "Non-finite RDF floats require an explicit lexical datatype"
            )
        raw, datatype = repr(raw), XSD + "double"
    elif not isinstance(raw, str):
        raise TypeError(
            "RDF literals support strings, numbers, booleans; expand objects/lists explicitly"
        )
    return _quoted(raw) + (
        "@" + value.language
        if value.language
        else ("^^<" + datatype + ">" if datatype else "")
    )


class RDF(BaseTarget):
    def __init__(self, format="ntriples"):
        if format not in ("ntriples", "nquads", "sparql"):
            raise ValueError("RDF format must be ntriples, nquads, or sparql")
        self.format = format

    def validate(self, declarations):
        for d in declarations:
            if not isinstance(d, TripleDeclaration):
                raise TypeError("RDF target requires graph declarations")
            if d.action == "retract" and self.format != "sparql":
                raise ValueError(
                    "RDF files represent assertions; use SPARQL for retractions"
                )
            if d.graph is not None and self.format == "ntriples":
                raise ValueError("Named graphs require N-Quads or SPARQL")

    def encode(self, operations):
        lines = []
        for op in operations:
            triple = " ".join(map(term, (op.subject, op.predicate, op.object)))
            if self.format == "nquads":
                lines.append(
                    triple
                    + (" " + term(op.graph) if op.graph is not None else "")
                    + " .\n"
                )
            elif self.format == "ntriples":
                lines.append(triple + " .\n")
            else:
                body = triple + " ."
                if op.graph is not None:
                    body = "GRAPH " + term(op.graph) + " { " + body + " }"
                lines.append(
                    ("INSERT" if op.action == "assert" else "DELETE")
                    + " DATA { "
                    + body
                    + " };\n"
                )
        return Batch(
            {"ntriples": "graph.nt", "nquads": "graph.nq", "sparql": "graph.ru"}[
                self.format
            ],
            {
                "ntriples": "application/n-triples",
                "nquads": "application/n-quads",
                "sparql": "application/sparql-update",
            }[self.format],
            len(operations),
            text="".join(lines),
        )
