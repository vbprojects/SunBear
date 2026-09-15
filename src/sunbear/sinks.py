"""Explicit ordered output persistence, independent of computation caches."""
import json
import os
from pathlib import Path
import tempfile
from ._codec import _encoded


def write_jsonl(tree, path):
    """Consume finite output; atomically publish only a successfully completed run.

    Preserve row order and duplicates. An existing destination remains intact if
    execution or serialization fails. Returns the destination Path.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for row in tree.iter_rows():
                f.write(_encoded(row) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return path


def read_jsonl(path):
    """Replayable file source. Each traversal reopens the file."""
    from .tree import DataTree
    def rows():
        with open(path, encoding="utf-8") as f:
            for line in f:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise TypeError("JSONL rows must be objects")
                yield value
    return DataTree.from_iter_factory(rows)
