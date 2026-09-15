"""Shared row-local API. Each method lowers to the same statement plan."""

from .expr import lower as ops
from .expr.ast import Expr, Path, _wrap
from .expr._sugar import all_of, any_of


class Fluent:
    __slots__ = ()

    def where(self, *predicates):
        return self.expr(ops.keep(all_of(*predicates)))

    def where_any(self, *predicates):
        return self.expr(ops.keep(any_of(*predicates)))

    def reject(self, *predicates):
        return self.expr(ops.keep(~all_of(*predicates)))

    def select(self, *fields, **named):
        return self.expr(ops.select(*fields, **named))

    def assign(self, **fields):
        return self.expr(ops.assign(**fields))

    def set(self, path, value):
        return self.expr(ops.assign(path, value))

    def update(self, path, builder):
        if not callable(builder):
            raise TypeError("update expects an expression builder")
        return self.set(path, builder(path if isinstance(path, Expr) else Path(path)))

    def drop(self, *paths):
        return self.expr(ops.drop(*paths))

    def rename(self, **mapping):
        return self.expr(ops.rename(**mapping))

    def copy(self, src, dst):
        return self.expr(ops.copy_field(src, dst))

    def nest(self, *paths, into):
        return self.expr(ops.nest(*paths, into=into))

    def unnest(self, path, *, prefix=""):
        return self.expr(("unnest_prefix", _wrap(path), prefix))

    def require(self, predicate, message=None):
        return self.expr(ops.assert_(predicate, message))

    def pipe(self, transform):
        return transform(self)

    def when(self, predicate):
        return Branch(self, predicate)

    def transform_fields(self, selector, builder):
        from .expr._sugar import item

        token = item("field_value")
        return self.expr(("transform_fields", selector, builder(token)))

    def rename_fields(self, selector, builder):
        return self.expr(("rename_fields", selector, builder))

    def require_fields(self, *fields):
        return self.expr(("require_fields", tuple(fields)))

    def drop_nulls(self, *fields):
        return self.expr(("drop_nulls", tuple(fields)))

    def emit(self, *outputs):
        from .emit import Emission

        return Emission(self, outputs)


class Branch:
    def __init__(self, parent, predicate, yes=None):
        self.parent, self.predicate, self.yes = parent, predicate, yes

    def then(self, program):
        from .program import Program

        if self.yes is not None or not isinstance(program, Program):
            raise TypeError("then() expects one Program")
        return Branch(self.parent, self.predicate, program)

    def otherwise(self, program):
        from .program import Program

        if self.yes is None or not isinstance(program, Program):
            raise TypeError("Complete then() and provide a Program")
        return self.parent.expr(
            ops.fork(self.predicate, self.yes._statements, program._statements)
        )

    def end(self):
        from .program import Program

        return self.otherwise(Program())
