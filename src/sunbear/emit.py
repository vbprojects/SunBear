"""Typed, streaming write declarations. No database connections or execution."""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Protocol, Iterable
import copy
from .paths import MISSING, output_value
from .expr.ast import _wrap
from .expr.eval import compile as compile_expr
from ._codec import _encoded, _json_value


@dataclass(frozen=True)
class RowWrite:
    destination: str
    values: dict
    key: tuple = ()
    mode: str = "insert"
    schema: tuple = ()


@dataclass(frozen=True)
class DocumentWrite:
    destination: str
    value: dict
    key: object = None
    mode: str = "insert"


@dataclass(frozen=True)
class Batch:
    """One caller-owned output. statements pair SQL text with bound parameters.

    byte_size counts UTF-8 output and serialized parameters, excluding source
    metadata. Yielding a batch makes no claim about backend acknowledgement.
    """

    destination: str
    content_type: str
    operation_count: int
    text: str = ""
    payload: object = None
    statements: tuple = ()
    source_tokens: tuple = ()

    @property
    def byte_size(self):
        return (
            len(self.text.encode("utf-8"))
            + (
                len(_encoded(self.payload).encode("utf-8"))
                if self.payload is not None
                else 0
            )
            + sum(
                len(_encoded(list(params)).encode("utf-8"))
                for _, params in self.statements
            )
        )


@dataclass(frozen=True)
class Artifact:
    destination: str
    text: str
    content_type: str = "text/plain"


class Target(Protocol):
    """Extension protocol. A fresh session owns any frozen schema per stream."""

    def validate(self, declarations): ...
    def session(self): ...
    def encode(self, operations) -> Batch: ...
    def artifacts(self, declarations) -> Iterable[Artifact]: ...


class EmissionError(ValueError):
    def __init__(self, row, destination, cause):
        self.row, self.destination = row, destination
        super().__init__(f"Output row {row}, destination {destination}: {cause}")


@dataclass(frozen=True)
class Row:
    destination: str
    key: tuple = ()
    mode: str = "insert"
    fields: tuple = ()
    schema: tuple = ()

    def __post_init__(self):
        _destination(self.destination)
        if self.mode not in ("insert", "upsert", "delete"):
            raise ValueError("Row mode must be insert, upsert, or delete")
        if self.mode != "insert" and not self.key:
            raise ValueError("upsert/delete requires key columns")
        if len(set(self.key)) != len(self.key) or not all(
            isinstance(k, str) and k for k in self.key
        ):
            raise ValueError("Invalid key columns")
        if self.schema:
            names = [k for k, _ in self.schema]
            if not set(self.key) <= set(names):
                raise ValueError("Key columns must appear in schema")

    def evaluator(self):
        fields = [(k, compile_expr(_wrap(v))) for k, v in self.fields]

        def evaluate(record):
            value = (
                output_value({k: fn(record) for k, fn in fields})
                if fields
                else record.data
            )
            _json_value(value)
            for key in self.key:
                if key not in value or value[key] is None:
                    raise ValueError(f"Missing/null row key: {key}")
            yield RowWrite(
                self.destination, copy.deepcopy(value), self.key, self.mode, self.schema
            )

        return evaluate


@dataclass(frozen=True)
class Document:
    destination: str
    key: object = None
    mode: str = "insert"
    value: object = None

    def __post_init__(self):
        _destination(self.destination)
        if self.mode not in ("insert", "replace", "update", "delete"):
            raise ValueError("Unsupported document mode")
        if self.mode != "insert" and self.key is None:
            raise ValueError("Document mutation requires a key expression")

    def evaluator(self):
        key = compile_expr(_wrap(self.key))
        value = (
            compile_expr(_wrap(self.value))
            if self.value is not None
            else lambda r: r.data
        )

        def evaluate(record):
            identity = key(record)
            if identity is MISSING or (identity is None and self.mode != "insert"):
                raise ValueError("Missing/null document key")
            if identity is not None and type(identity) not in (str, int):
                raise TypeError("Document keys must be strings or integers")
            body = {} if self.mode == "delete" else value(record)
            if not isinstance(body, dict):
                raise TypeError("Document body must be an object")
            _json_value(body)
            yield DocumentWrite(
                self.destination, copy.deepcopy(body), identity, self.mode
            )

        return evaluate


def _destination(value):
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("Destination must be a nonempty string without NUL")


def row(destination, *, key=(), mode="insert", schema=None, **fields):
    return Row(
        destination,
        (key,) if isinstance(key, str) else tuple(key),
        mode,
        tuple(fields.items()),
        tuple((schema or {}).items()),
    )


def document(destination, *, key=None, mode="insert", value=None):
    return Document(destination, key, mode, value)


class Emission:
    def __init__(self, source, declarations):
        if not declarations:
            raise ValueError("At least one output declaration is required")
        self.source, self.declarations = source, copy.deepcopy(tuple(declarations))
        self._evaluators = tuple(d.evaluator() for d in self.declarations)

    def compile(self, target):
        target.validate(self.declarations)
        return Job(self, target)


class Job:
    def __init__(self, emission, target):
        self.emission, self.target = emission, copy.deepcopy(target)

    def artifacts(self):
        return tuple(self.target.artifacts(self.emission.declarations))

    def stream(
        self, source=None, *, batch_rows=500, batch_bytes=1_048_576, source_token=None
    ):
        from .tree import DataTree
        from .program import Program

        if type(batch_rows) is not int or batch_rows < 1:
            raise ValueError("batch_rows must be positive")
        if type(batch_bytes) is not int or batch_bytes < 1:
            raise ValueError("batch_bytes must be positive")
        if source_token is not None and not callable(source_token):
            raise TypeError("source_token must be callable")
        origin = self.emission.source
        if isinstance(origin, Program):
            if source is None:
                raise TypeError("A Program output job requires a source")
            tree = origin(
                source if isinstance(source, DataTree) else DataTree.from_iter(source)
            )
        else:
            if source is not None:
                raise TypeError("This output job already has a source")
            tree = origin
        target = self.target.session()

        def generate():
            buffer = _BatchBuffer(
                target, batch_rows, batch_bytes, source_token is not None
            )
            for index, (record, meta) in enumerate(tree.scan()):
                token = source_token(meta) if source_token else None
                for operation in self._operations(record, index):
                    try:
                        batch = buffer.add(operation, token)
                    except Exception as exc:
                        raise EmissionError(index, operation.destination, exc) from exc
                    if batch is not None:
                        yield batch
            if buffer.pending:
                yield buffer.finish()

        return generate()

    def _operations(self, record, index):
        for declaration, evaluate in zip(
            self.emission.declarations, self.emission._evaluators
        ):
            try:
                yield from evaluate(record)
            except Exception as exc:
                raise EmissionError(
                    index,
                    getattr(declaration, "destination", type(declaration).__name__),
                    exc,
                ) from exc

    def astream(
        self,
        source,
        *,
        batch_rows=500,
        batch_bytes=1_048_576,
        source_token=None,
        close_source=True,
    ):
        """Incrementally transform an async source of dicts using the same row plan.

        Explicit aclose() or cancellation closes the source by default and
        flushes an explicitly configured computation cache. Partial batches are
        discarded on errors; only yielded batches are caller-owned outputs.
        """
        from .program import Program
        from .record import Record

        program = self.emission.source
        if not isinstance(program, Program):
            raise TypeError("astream requires a Program output job")
        if (
            type(batch_rows) is not int
            or batch_rows < 1
            or type(batch_bytes) is not int
            or batch_bytes < 1
        ):
            raise ValueError("Batch limits must be positive integers")
        if source_token is not None and not callable(source_token):
            raise TypeError("source_token must be callable")

        async def generate():
            iterator = aiter(source)
            buffer = _BatchBuffer(
                self.target.session(), batch_rows, batch_bytes, source_token is not None
            )
            index = 0
            try:
                async for value in iterator:
                    if not isinstance(value, dict):
                        raise TypeError("Async source must yield dictionaries")
                    record = program._execute_record(
                        Record(value, {"i": index}), row=index
                    )
                    if record is not None:
                        token = source_token(record.meta) if source_token else None
                        for operation in self._operations(record, index):
                            try:
                                batch = buffer.add(operation, token)
                            except Exception as exc:
                                raise EmissionError(
                                    index, operation.destination, exc
                                ) from exc
                            if batch is not None:
                                yield batch
                    index += 1
                if buffer.pending:
                    yield buffer.finish()
            finally:
                try:
                    if program._cache is not None:
                        program._cache.flush()
                finally:
                    if close_source and hasattr(iterator, "aclose"):
                        await iterator.aclose()

        return generate()


class _BatchBuffer:
    def __init__(self, target, rows, size, tokens):
        self.target, self.rows, self.limit, self.with_tokens = (
            target,
            rows,
            size,
            tokens,
        )
        self.pending, self.tokens, self.size, self.destination = [], [], 0, None

    def add(self, operation, token):
        unit = self.target.encode([operation])
        if unit.byte_size > self.limit:
            raise ValueError(f"One operation exceeds batch_bytes={self.limit}")
        key = (
            self.target.batch_key(operation)
            if hasattr(self.target, "batch_key")
            else unit.destination
        )
        batch = None
        if self.pending and (
            len(self.pending) >= self.rows
            or self.size + unit.byte_size > self.limit
            or key != self.destination
        ):
            batch = self.finish()
        self.destination = key
        self.pending.append(operation)
        self.size += unit.byte_size
        if self.with_tokens:
            self.tokens.append(copy.deepcopy(token))
        return batch

    def finish(self):
        result = _batch(self.target, self.pending, self.tokens, self.limit)
        self.pending, self.tokens, self.size = [], [], 0
        return result


def _batch(target, operations, tokens, limit):
    from dataclasses import replace

    result = target.encode(operations)
    if result.byte_size > limit:
        raise ValueError(
            "Target encoded a batch larger than the sum of its individual operations"
        )
    return replace(result, source_tokens=tuple(tokens))
