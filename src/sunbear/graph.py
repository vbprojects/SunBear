"""Experimental declarative graph mapping to typed RDF statements."""

from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import quote, urlsplit
from .expr.ast import _wrap
from .expr.eval import compile as compile_expr
from .paths import MISSING

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"


@dataclass(frozen=True)
class IRI:
    value: str

    def __post_init__(self):
        if not isinstance(self.value, str) or not urlsplit(self.value).scheme:
            raise ValueError("RDF IRIs must be absolute")
        if any(ord(c) <= 32 or c in '<>"{}|^`\\' for c in self.value):
            raise ValueError("Invalid RDF IRI character")


@dataclass(frozen=True)
class Literal:
    value: object
    datatype: str | None = None
    language: str | None = None

    def __post_init__(self):
        import re

        if self.datatype and self.language:
            raise ValueError("Choose datatype or language")
        if self.datatype:
            IRI(self.datatype)
        if self.language and not re.fullmatch(
            r"[a-zA-Z]+(?:-[a-zA-Z0-9]+)*", self.language
        ):
            raise ValueError("Invalid RDF language tag")


@dataclass(frozen=True)
class Ref:
    kind: str
    value: object


@dataclass(frozen=True)
class Triple:
    subject: IRI
    predicate: IRI
    object: IRI | Literal
    graph: IRI | None = None
    action: str = "assert"

    @property
    def destination(self):
        return self.graph.value if self.graph is not None else "graph"


def ref(kind, value):
    if not isinstance(kind, str) or not kind:
        raise ValueError("Reference kind must be a nonempty string")
    return Ref(kind, value)


def iri(value):
    return IRI(value)


def literal(value, *, datatype=None, language=None):
    return Literal(value, datatype, language)


def _reference(namespace, kind, identity):
    if type(identity) not in (str, int):
        raise TypeError("Entity IDs must be non-null strings or integers")
    return IRI(
        namespace
        + quote(kind, safe="")
        + "/"
        + ("i/" if type(identity) is int else "s/")
        + quote(str(identity), safe="")
    )


def _term(value, namespace, *, resource=False):
    if isinstance(value, Ref):
        fn = compile_expr(_wrap(value.value))

        def evaluate(r):
            return _reference(namespace, value.kind, fn(r))

        return evaluate
    if isinstance(value, IRI):
        return lambda r: value
    if resource:
        if not isinstance(value, str):
            raise TypeError("Resource requires an IRI, ref(), or static name")
        term = IRI(
            value if urlsplit(value).scheme else namespace + quote(value, safe="")
        )
        return lambda r: term
    if isinstance(value, Literal):
        fn = compile_expr(_wrap(value.value))
        return lambda r: Literal(fn(r), value.datatype, value.language)
    fn = compile_expr(_wrap(value))
    return lambda r: Literal(fn(r))


@dataclass(frozen=True)
class TripleDeclaration:
    namespace: str
    subject: object
    predicate: object
    object: object
    when: object = True
    graph: object = None
    action: str = "assert"
    nulls: str = "omit"
    many: bool = False
    destination: str = "graph"

    def evaluator(self):
        if self.action not in ("assert", "retract"):
            raise ValueError("Triple action must be assert or retract")
        if self.nulls not in ("omit", "raise"):
            raise ValueError("nulls must be omit or raise")
        subject, predicate = (
            _term(self.subject, self.namespace, resource=True),
            _term(self.predicate, self.namespace, resource=True),
        )
        cond = compile_expr(_wrap(self.when))
        graph = (
            _term(self.graph, self.namespace, resource=True)
            if self.graph is not None
            else lambda r: None
        )
        obj = _term(self.object, self.namespace)
        if self.many:
            if not isinstance(self.object, Ref):
                raise TypeError("edges requires ref(kind, list_expression)")
            values = compile_expr(_wrap(self.object.value))

        def evaluate(r):
            if not bool(cond(r)):
                return
            if self.many:
                ids = values(r)
                if ids is None or ids is MISSING:
                    if self.nulls == "omit":
                        return
                    raise ValueError("Missing/null relationship list")
                if not isinstance(ids, list):
                    raise TypeError("edges requires list-valued IDs")
                objects = (
                    _reference(self.namespace, self.object.kind, value) for value in ids
                )
            else:
                objects = (obj(r),)
            for value in objects:
                if isinstance(value, Literal) and (
                    value.value is None or value.value is MISSING
                ):
                    if self.nulls == "omit":
                        continue
                    raise ValueError("RDF has no implicit null literal")
                yield Triple(subject(r), predicate(r), value, graph(r), self.action)

        return evaluate


@dataclass(frozen=True)
class Mapping:
    namespace: str
    declarations: tuple = ()
    nulls: str = "omit"

    def __post_init__(self):
        IRI(self.namespace)
        if not self.namespace.endswith(("/", "#", ":")):
            raise ValueError("namespace must end in /, #, or :")
        if self.nulls not in ("omit", "raise"):
            raise ValueError("nulls must be omit or raise")

    def triple(
        self, subject, predicate, object, *, when=True, graph=None, action="assert"
    ):
        from dataclasses import replace

        declaration = TripleDeclaration(
            self.namespace, subject, predicate, object, when, graph, action, self.nulls
        )
        declaration.evaluator()
        return replace(self, declarations=(*self.declarations, declaration))

    def node(self, identity, *, kind=None, when=True, graph=None, **properties):
        result = self
        if kind is not None:
            result = result.triple(
                identity,
                IRI(RDF_TYPE),
                IRI(
                    kind
                    if urlsplit(kind).scheme
                    else self.namespace + quote(kind, safe="")
                ),
                when=when,
                graph=graph,
            )
        for name, value in properties.items():
            result = result.triple(identity, name, value, when=when, graph=graph)
        return result

    def edge(self, subject, predicate, object, **options):
        return self.triple(subject, predicate, object, **options)

    def edges(
        self, subject, predicate, objects, *, when=True, graph=None, action="assert"
    ):
        from dataclasses import replace

        declaration = TripleDeclaration(
            self.namespace,
            subject,
            predicate,
            objects,
            when,
            graph,
            action,
            self.nulls,
            True,
        )
        declaration.evaluator()
        return replace(self, declarations=(*self.declarations, declaration))

    def relationship(
        self,
        identity,
        subject,
        predicate,
        object,
        *,
        when=True,
        assert_edge=False,
        **properties,
    ):
        """RDF statement reification with a caller-assigned relationship identity."""
        rdf = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
        result = self.node(identity, kind=rdf + "Statement", when=when, **properties)
        result = result.edge(identity, IRI(rdf + "subject"), subject, when=when)
        predicate_iri = (
            predicate
            if isinstance(predicate, IRI)
            else IRI(
                predicate
                if urlsplit(predicate).scheme
                else self.namespace + quote(predicate, safe="")
            )
        )
        result = result.edge(identity, IRI(rdf + "predicate"), predicate_iri, when=when)
        result = result.edge(identity, IRI(rdf + "object"), object, when=when)
        return (
            result.edge(subject, predicate, object, when=when)
            if assert_edge
            else result
        )

    def then(self, other):
        from dataclasses import replace

        if not isinstance(other, Mapping) or other.namespace != self.namespace:
            raise ValueError("Mappings must share a namespace")
        return replace(self, declarations=(*self.declarations, *other.declarations))

    def emit(self, source=None):
        from .emit import Emission
        from .program import Program

        return Emission(Program() if source is None else source, self.declarations)

    def compile(self, target):
        return self.emit().compile(target)
