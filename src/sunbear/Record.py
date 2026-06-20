"""record.py — row payload with path-based get/set/mv/add and indexer sugar."""


class _Missing:
    """Sentinel singleton that survives deepcopy and pickle."""
    _inst = None

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __deepcopy__(self, memo):
        return self

    def __reduce__(self):
        return (_Missing, ())

    def __repr__(self):
        return "<MISSING>"


_MISSING = _Missing()


def _deep_merge(dst: dict, src: dict) -> dict:
    """Recursively merge src into dst in-place."""
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _freeze(v):
    """Make get_leaves output hashable so it can be a group key."""
    if isinstance(v, list):
        return tuple(_freeze(x) for x in v)
    if isinstance(v, dict):
        return tuple(sorted((k, _freeze(x)) for k, x in v.items()))
    return v


def construct_schema(record: dict):
    """Infer a type-level schema from a record dict."""

    def _walk(node):
        return (
            {k: _walk(v) for k, v in node.items()}
            if isinstance(node, dict)
            else type(node).__name__
        )

    return _walk(record)


class Record:
    """Row payload with path-based get/set/mv/add and indexer sugar."""

    def __init__(self, data: dict):
        self.data = data

    def __eq__(self, other):
        return isinstance(other, Record) and self.data == other.data

    __hash__ = None

    def __repr__(self):
        return f"Record({self.data!r})"

    # ---- indexer resolution: str | dotted-str | tuple | list | dict ----

    @classmethod
    def _resolve_indexer(cls, indexer) -> dict:
        if isinstance(indexer, dict):
            return indexer  # already resolved
        if isinstance(indexer, str):
            path = {}
            parts = indexer.split(".")
            cur = path
            for k in parts[:-1]:
                cur[k] = {}
                cur = cur[k]
            cur[parts[-1]] = {}
            return path
        if isinstance(indexer, (list, tuple)):
            merged = {}
            for ix in indexer:
                _deep_merge(merged, cls._resolve_indexer(ix))
            return merged
        raise TypeError(f"unsupported indexer: {indexer!r}")

    # ---- walkers ----

    @staticmethod
    def _walk_get(node, path):
        if not isinstance(path, dict) or len(path) == 0:
            return node
        if node is None:
            return None
        if isinstance(node, list):
            merged = {}
            for item in node:
                r = Record._walk_get(item, path)
                if isinstance(r, dict):
                    for k, v in r.items():
                        merged.setdefault(k, []).append(v)
            return merged or None
        if not isinstance(node, dict):
            return None
        return {k: Record._walk_get(node.get(k), sub) for k, sub in path.items()}

    @staticmethod
    def _walk_set(node, path, value):
        for k, sub in path.items():
            if isinstance(sub, dict) and sub:
                if not isinstance(node.get(k), dict):
                    node[k] = {}
                Record._walk_set(node[k], sub, value)
            else:
                node[k] = value

    @staticmethod
    def _walk_delete(node, path):
        keys = list(path.keys())
        cur = node
        for k in keys[:-1]:
            if not isinstance(cur.get(k), dict):
                return
            cur = cur[k]
        cur.pop(keys[-1], None)

    # ---- public, indexer-accepting API ----

    def get(self, indexer):
        return self._walk_get(self.data, self._resolve_indexer(indexer))

    def get_leaves(self, indexer):
        def _leaves(v):
            if isinstance(v, dict):
                return (
                    _leaves(next(iter(v.values())))
                    if len(v) == 1
                    else [_leaves(x) for x in v.values()]
                )
            if isinstance(v, list):
                return [_leaves(x) for x in v]
            return v

        return _leaves(self.get(indexer))

    def set(self, indexer, value):
        self._walk_set(self.data, self._resolve_indexer(indexer), value)

    def add(self, indexer, value):
        if self.get(indexer) is None:
            self.set(indexer, value)

    def mv(self, src, dst):
        val = self.get_leaves(src)
        self._walk_delete(self.data, self._resolve_indexer(src))
        self.set(dst, val)

    def cpy_mv(self, src, dst):
        self.set(dst, self.get_leaves(src))

    # ---- sugar ----

    def __getitem__(self, indexer):  # record["a.b"]
        return self.get_leaves(indexer)

    def __setitem__(self, indexer, value):  # record["a.b"] = v
        self.set(indexer, value)

    def __contains__(self, indexer):  # "a.b" in record
        return self.get(indexer) is not None