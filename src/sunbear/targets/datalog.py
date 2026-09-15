"""Souffle code generation with separate setup and streamed facts."""

from ._base import BaseTarget, Batch, Artifact
from ..logic import Facts, Rule, Output, Variable, validate_value


def _constant(value):
    if isinstance(value, str):
        if any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError(
                "Souffle symbols cannot contain control characters in this target"
            )
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)


def _atom(atom):
    terms = [t.name if isinstance(t, Variable) else _constant(t) for t in atom.terms]
    return atom.relation.name + "(" + ", ".join(terms) + ")"


class Datalog(BaseTarget):
    def __init__(self, dialect="souffle", *, output="files"):
        if dialect != "souffle":
            raise ValueError("The supported Datalog dialect is souffle")
        if output not in ("files", "inline"):
            raise ValueError("Datalog output must be files or inline")
        self.output = output

    def _relations(self, declarations):
        relations = {}
        for declaration in declarations:
            if isinstance(declaration, Facts):
                atoms = (declaration.atom,)
            elif isinstance(declaration, Rule):
                atoms = (declaration.head, *declaration.body)
            elif isinstance(declaration, Output):
                relation = declaration.relation
                atoms = (
                    relation(
                        *[Variable("V" + str(i)) for i in range(len(relation.fields))]
                    ),
                )
            else:
                raise TypeError("Datalog target requires logic declarations")
            for atom in atoms:
                relation = atom.relation
                if relation.name in relations and relation != relations[relation.name]:
                    raise ValueError("Conflicting relation declarations")
                relations[relation.name] = relation
        return relations

    def validate(self, declarations):
        self._relations(declarations)
        for declaration in declarations:
            if isinstance(declaration, Rule):
                _atom(declaration.head)
                [_atom(a) for a in declaration.body]

    def artifacts(self, declarations):
        relations = self._relations(declarations)
        lines = [
            f".decl {r.name}("
            + ", ".join(f"{name}:{type_}" for name, type_ in r.fields)
            + ")\n"
            for r in relations.values()
        ]
        if self.output == "files":
            for name in dict.fromkeys(
                d.atom.relation.name for d in declarations if isinstance(d, Facts)
            ):
                lines.append(f".input {name}\n")
        for d in declarations:
            if isinstance(d, Rule):
                lines.append(
                    _atom(d.head) + " :- " + ", ".join(_atom(a) for a in d.body) + ".\n"
                )
        for name in dict.fromkeys(
            d.relation.name for d in declarations if isinstance(d, Output)
        ):
            lines.append(f".output {name}\n")
        yield Artifact("program.dl", "".join(lines))

    def encode(self, operations):
        lines = []
        for op in operations:
            for value, (_, type_) in zip(op.values, op.relation.fields):
                validate_value(value, type_)
            if self.output == "inline":
                lines.append(
                    op.relation.name
                    + "("
                    + ", ".join(map(_constant, op.values))
                    + ").\n"
                )
            else:
                # Souffle's default .facts format is raw TSV, with no CSV quoting.
                # Reject unrepresentable fields instead of silently changing values.
                values = list(map(str, op.values))
                if any(
                    any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in v)
                    for v in values
                ):
                    raise ValueError(
                        "Souffle TSV symbols cannot contain control characters"
                    )
                lines.append("\t".join(values) + "\n")
        destination = (
            "facts.dl"
            if self.output == "inline"
            else operations[0].relation.name + ".facts"
        )
        return Batch(destination, "text/plain", len(operations), text="".join(lines))
