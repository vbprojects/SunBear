"""PostgreSQL and SQLite INSERT/UPSERT/DELETE compilers."""

from urllib.parse import quote

from ._base import BaseTarget, identifier, Batch, Artifact
from ..emit import Row
from .._codec import _encoded

_TYPES = {
    "postgresql": {
        "text": "TEXT",
        "integer": "BIGINT",
        "real": "DOUBLE PRECISION",
        "boolean": "BOOLEAN",
        "json": "JSONB",
    },
    "sqlite": {
        "text": "TEXT",
        "integer": "INTEGER",
        "real": "REAL",
        "boolean": "INTEGER",
        "json": "TEXT",
    },
}


class SQL(BaseTarget):
    def __init__(self, dialect, *, output="script", parameter_style=None):
        if dialect not in _TYPES:
            raise ValueError("SQL dialect must be postgresql or sqlite")
        if output not in ("script", "parameters"):
            raise ValueError("SQL output must be script or parameters")
        styles = {"postgresql": ("numeric", "format"), "sqlite": ("qmark",)}
        self.parameter_style = parameter_style or styles[dialect][0]
        if self.parameter_style not in styles[dialect]:
            raise ValueError("Unsupported parameter style for dialect")
        self.dialect, self.output, self._schemas = dialect, output, {}

    def _identifier(self, value):
        quoted = identifier(value)
        if self.dialect == "postgresql" and len(value.encode("utf-8")) > 63:
            raise ValueError("PostgreSQL identifiers are limited to 63 UTF-8 bytes")
        return quoted

    def validate(self, declarations):
        known = {}
        for declaration in declarations:
            if not isinstance(declaration, Row):
                raise TypeError("SQL target requires emit.row declarations")
            self._identifier(declaration.destination)
            for name, type_ in declaration.schema:
                self._identifier(name)
                if type_ not in _TYPES[self.dialect]:
                    raise ValueError(f"Unsupported SQL type: {type_}")
            definition = (declaration.schema, declaration.key)
            previous = known.setdefault(declaration.destination, definition)
            if previous != definition:
                raise ValueError("Conflicting schemas or keys for a table")

    def artifacts(self, declarations):
        seen = set()
        for d in declarations:
            if not d.schema or d.destination in seen:
                continue
            seen.add(d.destination)
            columns = [
                f"{identifier(k)} {_TYPES[self.dialect][t]}"
                + (" NOT NULL" if k in d.key else "")
                for k, t in d.schema
            ]
            if d.key:
                columns.append(
                    "PRIMARY KEY (" + ", ".join(map(identifier, d.key)) + ")"
                )
            yield Artifact(
                quote(d.destination, safe="") + ".sql",
                f"CREATE TABLE IF NOT EXISTS {identifier(d.destination)} ("
                + ", ".join(columns)
                + ");\n",
                "application/sql",
            )

    def _columns(self, write):
        if write.mode == "delete":
            return write.key
        declared = tuple(k for k, _ in write.schema)
        columns = declared or self._schemas.setdefault(
            write.destination, tuple(write.values)
        )
        if set(columns) != set(write.values):
            raise ValueError(
                "Row columns differ from declared/frozen schema; use select and fill_missing explicitly"
            )
        if not columns:
            raise ValueError("SQL rows require at least one column")
        return columns

    def _value(self, value, type_=None):
        if value is None:
            return None
        if type_:
            valid = {
                "text": lambda v: isinstance(v, str),
                "integer": lambda v: type(v) is int,
                "real": lambda v: type(v) in (int, float),
                "boolean": lambda v: type(v) is bool,
                "json": lambda v: True,
            }[type_](value)
            if not valid:
                raise TypeError(f"Value does not match SQL {type_}")
        if type_ == "json":
            return _encoded(value)
        if isinstance(value, (dict, list)):
            raise TypeError("Nested SQL values need an explicit json column")
        if isinstance(value, str) and "\x00" in value:
            raise ValueError("SQL text cannot contain NUL")
        if type(value) is int and not -(2**63) <= value < 2**63:
            raise ValueError("SQL integer exceeds signed 64-bit range")
        return value

    def _literal(self, value):
        if value is None:
            return "NULL"
        if type(value) is bool:
            return "TRUE" if value else "FALSE"
        if type(value) in (int, float):
            return str(value)
        if self.dialect == "postgresql":
            return "E'" + value.replace("\\", "\\\\").replace("'", "''") + "'"
        return "'" + value.replace("'", "''") + "'"

    def _statement(self, write):
        columns = self._columns(write)

        def quote_name(value):
            quoted = self._identifier(value)
            return (
                quoted.replace("%", "%%")
                if self.output == "parameters" and self.parameter_style == "format"
                else quoted
            )

        schema = dict(write.schema)
        values = tuple(self._value(write.values[k], schema.get(k)) for k in columns)
        if self.output == "script":
            refs = [self._literal(v) for v in values]
        elif self.parameter_style == "numeric":
            refs = [f"${i}" for i in range(1, len(values) + 1)]
        elif self.parameter_style == "format":
            refs = ["%s"] * len(values)
        else:
            refs = ["?"] * len(values)
        table = quote_name(write.destination)
        if write.mode == "delete":
            sql = f"DELETE FROM {table} WHERE " + " AND ".join(
                f"{quote_name(k)} = {v}" for k, v in zip(columns, refs)
            )
        else:
            sql = (
                f"INSERT INTO {table} ("
                + ", ".join(map(quote_name, columns))
                + ") VALUES ("
                + ", ".join(refs)
                + ")"
            )
            if write.mode == "upsert":
                sql += (
                    " ON CONFLICT (" + ", ".join(map(quote_name, write.key)) + ") DO "
                )
                updates = [
                    f"{quote_name(k)} = excluded.{quote_name(k)}"
                    for k in columns
                    if k not in write.key
                ]
                sql += "UPDATE SET " + ", ".join(updates) if updates else "NOTHING"
        return sql + ";\n", values

    def encode(self, operations):
        statements = tuple(self._statement(op) for op in operations)
        return Batch(
            operations[0].destination,
            "application/sql",
            len(operations),
            text="".join(sql for sql, _ in statements),
            statements=statements if self.output == "parameters" else (),
        )
