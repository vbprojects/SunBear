from typing import *
from itertools import *
# A DataTree is a generator that yeilds a tuple of metadata and records zipped together

Branch = Iterator[Tuple['Record', Dict[str, Any]]]
operator = Callable[['Record', Dict[str, Any]], Tuple['Record', Dict[str, Any]]]
indexer = str | Tuple[str] | List[str]
Twig = Tuple['Record', Dict[str, Any]]


def construct_schema(record : Dict[str, Any]) -> Dict[str, Any]:
    def _walk(node : Dict[str, Any] | Any) -> Any:
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        else:
            return type(node).__name__
    return _walk(record)

def _resolve_path(indexer : str) -> Dict[str, Any]:
    elems = indexer.split('.')
    path = {}
    current = path
    
    # Iterate through all parts except the very last one
    for k in elems[:-1]:
        current[k] = {}
        # Move our pointer into the newly created nested dict
        current = current[k]
        
    # Set the final part to an empty dict (or you can assign a different value here)
    if elems:
        current[elems[-1]] = {}
        
    return path

def _resolve_indexer(indexer : str | Tuple[str] | List[str]) -> Dict[str, Any]:
    if isinstance(indexer, str):
        if '.' in indexer:
            return _resolve_path(indexer)


def identity(record, metadata):
    return record, {}

class Record:
    """Wraps a dict with path-based get/set/mv/add using resolved indexer dicts."""
    
    def __init__(self, data : Dict[str, Any]):
        self.data = data
    
    # -- internal helpers -------------------------------------------------
    @staticmethod
    def _walk_get(node : Any, path : Dict[str, Any]) -> Any:
        """Follow *path* into *node*; return the value at the leaf, or None."""
        if not isinstance(path, dict) or len(path) == 0:
            return node

        if node is None:
            return None

        # If node is a list, apply extraction to each element and merge results
        if isinstance(node, list):
            results = [Record._walk_get(item, path) for item in node]
            merged: Dict[str, Any] = {}
            for r in results:
                if isinstance(r, dict):
                    for k, v in r.items():
                        merged.setdefault(k, []).append(v)
            return merged if merged else None

        if not isinstance(node, dict):
            return None

        result = {}
        for k, subpath in path.items():
            result[k] = Record._walk_get(node.get(k), subpath)
        return result
    
    @staticmethod
    def _walk_set(node : Dict[str, Any], path : Dict[str, Any], value : Any) -> None:
        """Walk *path* into *node*, creating missing dicts, and set *value* at the leaf."""
        for k, subpath in path.items():
            if isinstance(subpath, dict) and len(subpath) > 0:
                if k not in node or not isinstance(node[k], dict):
                    node[k] = {}
                Record._walk_set(node[k], subpath, value)
            else:
                node[k] = value
    
    @staticmethod
    def _walk_delete(node : Dict[str, Any], path : Dict[str, Any]) -> None:
        """Delete the value at *path* inside *node*."""
        keys = list(path.keys())
        if not keys:
            return
        # Walk down to the parent of the leaf
        current = node
        for k in keys[:-1]:
            if not isinstance(current.get(k), dict):
                return
            current = current[k]
        # Delete the leaf key
        leaf_key = keys[-1]
        if leaf_key in current:
            del current[leaf_key]
    
    # -- public API -------------------------------------------------------
    def get(self, path : Dict[str, Any]) -> Any:
        """Return the value at *path*, or None if any segment is missing."""
        return self._walk_get(self.data, path)

    def get_leaves(self, path : Dict[str, Any]) -> Any:
        """Return leaf values for *path*, collapsing single-key dicts into their values."""
        def _leaves(value : Any) -> Any:
            if isinstance(value, dict):
                if len(value) == 1:
                    return _leaves(next(iter(value.values())))
                return [_leaves(v) for v in value.values()]
            if isinstance(value, list):
                return [_leaves(v) for v in value]
            return value

        return _leaves(self.get(path))
    
    def set(self, path : Dict[str, Any], value : Any) -> None:
        """Set *value* at *path*, creating intermediate dicts as needed."""
        self._walk_set(self.data, path, value)
    
    def mv(self, from_path : Dict[str, Any], to_path : Dict[str, Any]) -> None:
        """Move a value from *from_path* to *to_path*."""
        value = self.get(from_path)
        self._walk_delete(self.data, from_path)
        self.set(to_path, value)
    
    def cpy_mv(self, from_path : Dict[str, Any], to_path : Dict[str, Any]) -> None:
        """Copy a value from *from_path* to *to_path* without deleting the original."""
        value = self.get(from_path)
        self.set(to_path, value)
    
    def add(self, path : Dict[str, Any], value : Any) -> None:
        """Set *value* at *path* only if the path does not already exist."""
        existing = self.get(path)
        if existing is None:
            self.set(path, value)
    
    @classmethod
    def _resolve_indexer(cls, indexer : str | Tuple[str] | List[str]) -> Dict[str, Any]:
        if isinstance(indexer, str):
            if '.' in indexer:
                return _resolve_path(indexer)
            return {indexer: {}}
        return indexer  # type: ignore[return-value]


def _register(**kwargs) -> operator:
    def _register_op(record, metadata):
        resolved_indexers = {k: Record._resolve_indexer(v) for k, v in kwargs.items()}
        return record, {"register": resolved_indexers}
    return _register_op

from itertools import tee

def map_iteration(branches : Iterator[Tuple['Record', Dict[str, Any]]], pre_operator : operator, post_operator : operator) -> Branch:
    for record, metadatum in branches:
        pre_operated_record, pre_operated_metadata = pre_operator(record, metadatum)
        mid_metadatum = {**metadatum, **pre_operated_metadata}
        post_operated_record, post_operated_metadata = post_operator(pre_operated_record, mid_metadatum)
        post_metadatum = {**mid_metadatum, **post_operated_metadata}
        yield post_operated_record, post_metadatum


def filter_iteration(branches, condition) -> Branch:
    for record, metadata in branches:
        if condition(record, metadata):
            yield record, metadata

def insertion_iteration(branches, condition, operation) -> Branch:
    for record, metadata in branches:
        if condition(record, metadata):
            new_record, new_metadata = operation(record, metadata)
            yield new_record, {new_metadata}
        else:
            yield record, metadata

def one_to_many_iteration(branches, condition, operation) -> Branch:
    for record, metadata in branches:
        if condition(record, metadata):
            new_records = operation(record, metadata)
            for new_record in new_records:
                yield new_record, metadata
        else:
            yield record, metadata

from collections import defaultdict

def many_to_one_iteration(branches, key, operation) -> Branch:
    """Group *branches* by *key* (a callable) without requiring sorted input.

    Uses a dict to collect all twigs sharing the same key, then passes each
    group as an iterator to *operation*.  Groups appear in first-encounter order.
    """
    groups: Dict[Any, List[Twig]] = defaultdict(list)
    for twig in branches:
        groups[key(twig)].append(twig)

    for group_key, group_list in groups.items():
        new_record, metadata = operation(iter(group_list))
        yield new_record, {"group_key": group_key, **metadata}


class DataTree:
    def __init__(self, records : Iterator[Tuple[Dict[str, Any], Dict[str, Any]]]):
        self._records = records
        # self.pre_operator = pre_operator or identity
        # self.post_operator = post_operator or identity
    
    @classmethod
    def from_iterator(cls, iterator : Iterator[Dict[str, Any]], pre_operator : Optional[operator] = None, post_operator : Optional[operator] = None):
        return cls(((Record(record), {"index": i}) for i, record in enumerate(iterator)))
    
    def __iter__(self) -> Branch:
        self._records, to_iterate = tee(self._records, 2)
        # return map_iteration(to_iterate)
        for record, metadata in to_iterate:
            yield record, metadata

    def select(self, **kwargs) -> 'DataTree':
        """Creates new records by registering paths and extracting values from them."""
        def _select_op(record, metadata):
            return {k: record.get(metadata['register'][k]) for k in kwargs.keys()}, {"register" : None}
        return DataTree(map_iteration(self, _register(**kwargs), _select_op))
    
    def filter(self, func : Callable[["Record"], bool]) -> 'DataTree':
        return DataTree(filter_iteration(self, func))

    def _group_by_op_indexer(self, indexer):
        resolved_index = Record._resolve_indexer(indexer)
        counter = count()
        def _group_by_key(twig):
            record, metadata = twig
            group_key = record.get_leaves(resolved_index)
            return group_key
        def _group_by_op(group):
            return Record({"records": [{"data" : record.data, "metadata" : metadatum} for record, metadatum in group]}), {"index" : next(counter)}
        return _group_by_key, _group_by_op

    def group_by(self, key = None) -> 'DataTree':
        if key is None:
            def _group_by_metadata_register(twig):
                record, metadata = twig
                index = metadata['register'][0]
                return record.get_leaves(index)
            _group_by_metadata_register, group_by_op = self._group_by_op_indexer(key)
            return DataTree(many_to_one_iteration(self, _group_by_metadata_register, group_by_op))
        if isinstance(key, str) or isinstance(key, tuple) or isinstance(key, list):
            group_by_key, group_by_op = self._group_by_op_indexer(key)
            return DataTree(many_to_one_iteration(self, group_by_key, group_by_op))
        if callable(key):
            def _group_by_op(group):
                return Record({"records": [{"data": r.data, "metadata": m} for r, m in group]}), {}
            return DataTree(many_to_one_iteration(self, key, _group_by_op))
        return self    

    def col(self, **kwargs) -> List[Any]:
        """Collect values from the stream based on registered paths."""
        collected = []
        def _collect_op(record, metadata):
            return [record.get_leaves(metadata['register'][k]) for k in kwargs.keys()], {}
        collected.append([k for k in kwargs.keys()])
        for record, _ in map_iteration(self, _register(**kwargs), _collect_op):
            collected.append(record)
        return collected
    
    def head(self, n=5):
        for i, twig in enumerate(self):
            if i >= n:
                break
            yield twig
        
        

def __main__():
    records = [
        {"name": "Alice", "age": 35},
        {"name": "Bob", "age": 20},
        {"name": "Charlie", "age": 35},
        {"name": "David", "age": 35},
        {"name": "Eve", "age": 20, "education" : [{"institution": "University A", "degree": "BSc"}, {"institution": "University B", "degree": "MSc"}]},
        {"name": "Frank", "age": 20}
    ]
    tree = DataTree.from_iterator(records)
    # for record, metadata in tree.head(5).head(3):
        # print(record, metadata)
    # print(Record({"records": [{"name": "Alice", "ages": [30, 31]}, {"name": "Bob", "ages": [25, 27]}]}, ).get(Record._resolve_indexer("records.ages")))
    # print(tree.head(n=2).col(name = "name", age = "age"))
    # print(tree.group_by("age").col(name = ))
    for record, metadata in tree.group_by("age"):
        print(record.data, metadata)
if __name__ == "__main__":
    __main__()