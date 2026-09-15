"""Composable selectors over the keys present in each row."""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Selector:
    kind: str
    args: tuple = ()

    def __or__(self, other):
        return Selector("or", (self, _check(other)))

    def __and__(self, other):
        return Selector("and", (self, _check(other)))

    def __sub__(self, other):
        return Selector("minus", (self, _check(other)))

    def __invert__(self):
        return all() - self

    def matches(self, name):
        if self.kind == "all":
            return True
        if self.kind == "names":
            return name in self.args
        if self.kind == "starts":
            return name.startswith(self.args)
        if self.kind == "ends":
            return name.endswith(self.args)
        if self.kind == "regex":
            return re.search(self.args[0], name) is not None
        a, b = self.args
        if self.kind == "or":
            return a.matches(name) or b.matches(name)
        if self.kind == "and":
            return a.matches(name) and b.matches(name)
        if self.kind == "minus":
            return a.matches(name) and not b.matches(name)
        raise ValueError("Unknown selector")

    def resolve(self, keys):
        return [key for key in keys if self.matches(key)]


def _check(value):
    if not isinstance(value, Selector):
        raise TypeError("Expected a Selector")
    return value


def all():
    return Selector("all")


def names(*values):
    return Selector("names", values)


def starts_with(*prefixes):
    return Selector("starts", prefixes)


def ends_with(*suffixes):
    return Selector("ends", suffixes)


def matches(pattern):
    re.compile(pattern)
    return Selector("regex", (pattern,))
