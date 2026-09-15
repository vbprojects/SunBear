"""Explicit memoization, separate from saved output."""

import abc
import json
import copy
import os
import tempfile
import warnings
from pathlib import Path
from ._codec import _encoded, _json_value

_FILTERED = object()


class AbstractCache(abc.ABC):
    @abc.abstractmethod
    def get(self, row_key):
        """Return dict, _FILTERED, or None for a cache miss."""

    @abc.abstractmethod
    def set(self, row_key, output):
        """Store a dict, or None for a filtered input."""

    def flush(self):
        pass

    def to_DataTree(self):
        raise NotImplementedError


class FileCache(AbstractCache):
    """Strict JSON memoization. One writer per file; writes are atomic and batched."""

    def __init__(self, name, *, directory=".sunbear_cache", flush_every=100):
        if (
            not isinstance(name, str)
            or not name
            or Path(name).name != name
            or name in {".", ".."}
        ):
            raise ValueError("Cache name must be a simple filename")
        if type(flush_every) is not int or flush_every < 1:
            raise ValueError("flush_every must be a positive integer")
        self.name = name
        self._path = str(Path(directory) / (name + ".json"))
        self.flush_every = flush_every
        self._store = {}
        self._pending = 0
        if os.path.exists(self._path):
            with open(self._path, encoding="utf-8") as f:
                payload = json.load(f)
            if payload.get("format") != 1:
                raise ValueError("Unsupported cache format; choose a new cache file")
            self._store = _json_value(payload["entries"])

    def get(self, row_key):
        if row_key not in self._store:
            return None
        value = self._store[row_key]
        return _FILTERED if value is None else copy.deepcopy(value)

    def set(self, row_key, output):
        self._store[row_key] = copy.deepcopy(_json_value(output))
        self._pending += 1
        if self._pending >= self.flush_every:
            self.flush()

    def flush(self):
        if not self._pending:
            return
        path = Path(self._path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            dir=path.parent, prefix=path.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(_encoded({"format": 1, "entries": self._store}))
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary, path)
            self._pending = 0
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def to_DataTree(self):
        warnings.warn(
            "Cache entries are not a saved run; use write_jsonl()",
            DeprecationWarning,
            stacklevel=2,
        )
        from .tree import DataTree

        rows = [copy.deepcopy(v) for v in self._store.values() if v is not None]
        if not rows:
            raise ValueError("Cache has no non-filtered rows")
        return DataTree.from_records(rows)
