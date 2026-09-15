"""Experimental typed Datalog declarations; no embedded evaluation engine."""

from __future__ import annotations
from dataclasses import dataclass, replace
import re
from .expr.ast import _wrap
from .expr.eval import compile as compile_expr


def _name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", name):
        raise ValueError(
            "Datalog identifiers must start with a letter and contain letters, digits, underscores"
        )
    return name


@dataclass(frozen=True)
class Variable:
    name: str

    def __post_init__(self):
        _name(self.name)


@dataclass(frozen=True)
class Relation:
    name: str
    fields: tuple

    def __post_init__(self):
        _name(self.name)
        if not self.fields:
            raise ValueError("Relation needs at least one field")
        for name, type_ in self.fields:
            _name(name)
            if type_ not in ("symbol", "number", "unsigned", "float"):
                raise ValueError("Unsupported Souffle type")

    def __call__(self, *terms):
        if len(terms) != len(self.fields):
            raise ValueError(f"{self.name} requires {len(self.fields)} terms")
        return Atom(self, tuple(terms))


@dataclass(frozen=True)
class Atom:
    relation: Relation
    terms: tuple


@dataclass(frozen=True)
class Fact:
    relation: Relation
    values: tuple

    @property
    def destination(self):
        return self.relation.name


@dataclass(frozen=True)
class Facts:
    atom: Atom
    when: object = True

    @property
    def destination(self):
        return self.atom.relation.name

    def evaluator(self):
        if any(isinstance(t, Variable) for t in self.atom.terms):
            raise TypeError(
                "Facts require row expressions or constants, not logic variables"
            )
        functions = [compile_expr(_wrap(t)) for t in self.atom.terms]
        predicate = compile_expr(_wrap(self.when))

        def evaluate(r):
            if predicate(r):
                yield Fact(self.atom.relation, tuple(fn(r) for fn in functions))

        return evaluate


@dataclass(frozen=True)
class Rule:
    head: Atom
    body: tuple

    def __post_init__(self):
        if (
            not isinstance(self.head, Atom)
            or not self.body
            or not all(isinstance(a, Atom) for a in self.body)
        ):
            raise TypeError("Rules require a head and positive body atoms")
        bound = {t.name for a in self.body for t in a.terms if isinstance(t, Variable)}
        if not {t.name for t in self.head.terms if isinstance(t, Variable)} <= bound:
            raise ValueError(
                "Unsafe rule: every head variable must be bound by the body"
            )
        types = {}
        for atom in (self.head, *self.body):
            for term, (_, type_) in zip(atom.terms, atom.relation.fields):
                if isinstance(term, Variable):
                    if term.name in types and types[term.name] != type_:
                        raise TypeError(f"Inconsistent variable type: {term.name}")
                    types[term.name] = type_
                else:
                    validate_value(term, type_)

    def evaluator(self):
        return lambda r: iter(())


@dataclass(frozen=True)
class Output:
    relation: Relation

    def evaluator(self):
        return lambda r: iter(())


def validate_value(value, type_):
    import math

    if type_ == "symbol":
        valid = isinstance(value, str)
    elif type_ == "number":
        valid = type(value) is int and -(2**31) <= value < 2**31
    elif type_ == "unsigned":
        valid = type(value) is int and 0 <= value < 2**32
    else:
        valid = type(value) in (int, float) and math.isfinite(value)
    if not valid:
        raise TypeError(f"Invalid {type_} fact value: {value!r}")
    return value


def relation(name, **fields):
    return Relation(name, tuple(fields.items()))


def var(name):
    return Variable(name)


def fact(atom, *, when=True):
    return Facts(atom, when)


def rule(head, *body):
    return Rule(head, tuple(body))


@dataclass(frozen=True)
class Program:
    declarations: tuple = ()

    def facts(self, atom, *, when=True):
        return replace(self, declarations=(*self.declarations, fact(atom, when=when)))

    def rule(self, head, *body):
        return replace(self, declarations=(*self.declarations, rule(head, *body)))

    def output(self, *relations):
        return replace(
            self, declarations=(*self.declarations, *(Output(r) for r in relations))
        )

    def emit(self, source=None):
        from .program import Program as Transform
        from .emit import Emission

        return Emission(Transform() if source is None else source, self.declarations)

    def compile(self, target):
        return self.emit().compile(target)
