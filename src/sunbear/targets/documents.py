"""Document ingestion dialects: JSONL, Elasticsearch bulk, MongoDB commands, Kusto."""

import copy
import json
import re
from ._base import BaseTarget, Batch, Artifact
from ..emit import Document, Row
from .._codec import _encoded


class JSONL(BaseTarget):
    def validate(self, declarations):
        if not all(
            isinstance(d, (Row, Document)) and d.mode == "insert" for d in declarations
        ):
            raise TypeError("JSONL supports append/insert rows or documents only")

    def encode(self, operations):
        return Batch(
            operations[0].destination,
            "application/x-ndjson",
            len(operations),
            text="".join(
                _encoded(op.values if hasattr(op, "values") else op.value) + "\n"
                for op in operations
            ),
        )


class Elasticsearch(BaseTarget):
    def validate(self, declarations):
        for d in declarations:
            if not isinstance(d, Document):
                raise TypeError("Elasticsearch requires emit.document")
            if (
                not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", d.destination)
                or len(d.destination.encode()) > 255
            ):
                raise ValueError(
                    "Use a lowercase Elasticsearch index name starting with a letter or digit"
                )

    def encode(self, operations):
        lines = []
        for op in operations:
            action = {
                "insert": "create",
                "replace": "index",
                "update": "update",
                "delete": "delete",
            }[op.mode]
            metadata = {"_index": op.destination}
            if op.key is not None:
                identity = str(op.key)
                if len(identity.encode("utf-8")) > 512:
                    raise ValueError("Elasticsearch _id exceeds 512 bytes")
                metadata["_id"] = identity
            lines.append(_encoded({action: metadata}))
            if action != "delete":
                lines.append(
                    _encoded({"doc": op.value} if action == "update" else op.value)
                )
        return Batch(
            operations[0].destination,
            "application/x-ndjson",
            len(operations),
            text="\n".join(lines) + "\n",
        )


class MongoDB(BaseTarget):
    def validate(self, declarations):
        for d in declarations:
            if not isinstance(d, Document):
                raise TypeError("MongoDB requires emit.document")
            if "$" in d.destination or d.destination.startswith("system."):
                raise ValueError("Unsupported MongoDB collection name")

    def batch_key(self, operation):
        return operation.destination, {"replace": "update"}.get(
            operation.mode, operation.mode
        )

    def encode(self, operations):
        op = operations[0]
        mode = {"replace": "update"}.get(op.mode, op.mode)
        command = {mode: op.destination, "ordered": True}
        entries = []
        for op in operations:
            body = copy.deepcopy(op.value)
            if "_id" in body and op.key is not None and body["_id"] != op.key:
                raise ValueError("Document _id conflicts with declared key")
            if mode == "insert":
                if op.key is not None:
                    body["_id"] = op.key
                entries.append(body)
            elif mode == "delete":
                entries.append({"q": {"_id": op.key}, "limit": 1})
            else:
                if op.mode == "update":
                    body.pop("_id", None)
                    if any(k.startswith("$") or "." in k for k in body):
                        raise ValueError(
                            "MongoDB update fields cannot contain dots or start with $"
                        )
                    body = {"$set": body}
                elif any(k.startswith("$") for k in body):
                    raise ValueError("MongoDB replacement keys cannot start with $")
                entries.append(
                    {
                        "q": {"_id": op.key},
                        "u": body,
                        "upsert": op.mode == "replace",
                        "multi": False,
                    }
                )
        command[
            {"insert": "documents", "update": "updates", "delete": "deletes"}[mode]
        ] = entries
        return Batch(
            op.destination, "application/json", len(operations), payload=command
        )


class Kusto(JSONL):
    """JSON ingestion payload plus explicit table and JSON mapping artifacts."""

    def __init__(self, *, schema, mapping="sunbear"):
        self.schema = dict(schema)
        self.mapping = mapping
        if not self.schema:
            raise ValueError("Kusto requires an explicit schema")
        _kusto_name(mapping)
        for name, type_ in self.schema.items():
            _kusto_name(name)
            if type_ not in (
                "string",
                "long",
                "real",
                "bool",
                "datetime",
                "dynamic",
                "guid",
                "timespan",
            ):
                raise ValueError("Unsupported Kusto type")

    def validate(self, declarations):
        super().validate(declarations)
        for d in declarations:
            _kusto_name(d.destination)

    def artifacts(self, declarations):
        for destination in dict.fromkeys(d.destination for d in declarations):
            columns = ", ".join(f"{k}:{v}" for k, v in self.schema.items())
            mapping = [
                {"column": k, "datatype": v, "Properties": {"Path": "$." + k}}
                for k, v in self.schema.items()
            ]
            text = f".create table {destination} ({columns})\n"
            text += (
                f'.create table {destination} ingestion json mapping "{self.mapping}" '
                + json.dumps(_encoded(mapping))
                + "\n"
            )
            yield Artifact(destination + ".kql", text, "text/plain")

    def encode(self, operations):
        for op in operations:
            values = op.values if hasattr(op, "values") else op.value
            if set(values) != set(self.schema):
                raise ValueError("Kusto document differs from declared schema")
            for key, type_ in self.schema.items():
                value = values[key]
                if value is None:
                    continue
                expected = {
                    "string": (str,),
                    "long": (int,),
                    "real": (int, float),
                    "bool": (bool,),
                    "datetime": (str,),
                    "guid": (str,),
                    "timespan": (str,),
                    "dynamic": (str, int, float, bool, list, dict),
                }[type_]
                if type(value) not in expected:
                    raise TypeError(f"Invalid Kusto {type_} value in {key}")
                if type_ == "long" and not -(2**63) <= value < 2**63:
                    raise ValueError("Kusto long exceeds 64 bits")
        return super().encode(operations)


def _kusto_name(name):
    if not isinstance(name, str) or not re.fullmatch("[A-Za-z_][A-Za-z0-9_]*", name):
        raise ValueError("Kusto names must be simple identifiers")
