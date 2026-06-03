from typing import *
from itertools import *
# A DataTree is a generator that yeilds a tuple of metadata and records zipped together

branch = Iterator[Tuple[Dict[str, Any], Dict[str, Any]]]
operator = Callable[[Dict[str, Any], Dict[str, Any]], Tuple[Dict[str, Any], Dict[str, Any]]]
indexer = str | Tuple[str] | List[str]

def construct_schema(record : Dict[str, Any]) -> Dict[str, Any]:
    def _walk(node : Dict[str, Any] | Any) -> Any:
        if isinstance(node, dict):
            return {k: _walk(v) for k, v in node.items()}
        else:
            return type(node).__name__
    return _walk(record)


def construct_metadata(record : Dict[str, Any]) -> Dict[str, Any]:
    return {
        "schema": construct_schema(record)
    }

def yield_branches(branches : Iterator[Tuple[Dict[str, Any], Dict[str, Any]]], pre_operator : operator, post_operator : operator) -> branch:
    for record, metadatum in branches:
        pre_operated_record, pre_operated_metadata = pre_operator(record, metadatum)
        
        if pre_operated_metadata is None:
            continue
        if 'break' in pre_operated_metadata:
            break
        
        mid_metadatum = {**metadatum, **pre_operated_metadata}
        
        post_operated_record, post_operated_metadata = post_operator(pre_operated_record, mid_metadatum)
        
        if post_operated_metadata is None:
            continue
        if 'break' in post_operated_metadata:
            break
        
        post_metadatum = {**mid_metadatum, **post_operated_metadata}
        
        yield post_operated_record, post_metadatum

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


class DataTree:
    def __init__(self, records : Iterator[Tuple[Dict[str, Any], Dict[str, Any]]], pre_operator : Optional[operator] = None, post_operator : Optional[operator] = None):
        self._records = records
        self.pre_operator = pre_operator or identity
        self.post_operator = post_operator or identity
    
    @classmethod
    def from_iterator(cls, iterator : Iterator[Dict[str, Any]], pre_operator : Optional[operator] = None, post_operator : Optional[operator] = None):
        return cls(((Record(record), {"index": i}) for i, record in enumerate(iterator)), pre_operator, post_operator)
    
    def __iter__(self) -> branch:
        return yield_branches(self._records, self.pre_operator, self.post_operator)
    
    def head(self, n : int = 5) -> 'DataTree':
        counter = count()
        def _head_op(record, metadata):
            if next(counter) < n:
                return record, {}
            else:
                return record, {'break': True}
        return DataTree(self, _head_op, identity)

    
    
    def register(self, **kwargs) -> 'DataTree':
        """Promises to resolve paths and add them to metadata register for use in downstream operators."""
        def _register_op(record, metadata):
            resolved_indexers = {k: Record._resolve_indexer(v) for k, v in kwargs.items()}
            return record, {"register": resolved_indexers}
        return DataTree(self, _register_op, identity)
    
    def select(self, **kwargs) -> 'DataTree':
        """Creates new records by registering paths and extracting values from them."""
        def _select_op(record, metadata):
            return {k: record.get(metadata['register'][k]) for k in kwargs.keys()}, {"register" : None}
        return DataTree(self, _register(**kwargs), _select_op)

    
    def filter(self, func : Callable[["Record"], bool]) -> 'DataTree':
        def _filter_operation(record, metadata):
            if func(record):
                return record, {}
            else:
                return None, {}  # Filter out by returning None metadata
        return DataTree(self, _filter_operation, identity)

    def flat_map(self, func : Callable[["Record"], Iterable[Dict[str, Any]]]) -> 'DataTree':
        """Apply *func* to each record, which should return an iterable of new records to flatten into the stream."""
        def _flat_map_op(record, metadata):
            new_records = func(record)
            if not isinstance(new_records, Iterable):
                raise ValueError("flat_map function must return an iterable")
            return new_records, {}
        return DataTree(self, identity, _flat_map_op)
    
    def reduce(self, func: Callable[[Any, "Record"], Any], initial: Any = None) -> 'DataTree':
        """Lazily evaluates the tree into a single record using an accumulator function."""
        def _reduce_gen():
            iterator = iter(self)
            try:
                # Initialize accumulator
                acc = initial if initial is not None else next(iterator)[0]
                
                # Consume the stream dynamically upon evaluation
                for record, _ in iterator:
                    acc = func(acc, record)
                    
                # Wrap the final accumulated state into a Record for downstream pipelines
                final_record = acc if isinstance(acc, Record) else Record(acc) if isinstance(acc, dict) else Record({"result": acc})
                yield final_record, {"reduce": True}
                
            except StopIteration:
                if initial is not None:
                    final_record = Record(initial) if isinstance(initial, dict) else Record({"result": initial})
                    yield final_record, {"reduce": True}
        
        # Returns a pending generator inside a new DataTree
        return DataTree(_reduce_gen())

    def group_by(self, key_path: str, agg_func: Callable[[Any, "Record"], Any], initial: Any) -> 'DataTree':
        """Lazily groups records by a key and reduces them using agg_func."""
        def _group_gen():
            groups = {}
            path = Record._resolve_indexer(key_path)
            import copy
            
            # Consume all upstream records to build aggregation buckets
            for record, _ in self:
                key_val = record.get(path)
                
                # Convert unhashable types for dict keys
                if isinstance(key_val, list):
                    key_val = tuple(key_val)
                elif isinstance(key_val, dict):
                    key_val = tuple(key_val.items())
                    
                if key_val not in groups:
                    groups[key_val] = copy.deepcopy(initial)
                    
                groups[key_val] = agg_func(groups[key_val], record)
                
            # Once exhaustive processing is done, yield each group as a stream of new records
            for k, final_state in groups.items():
                yield Record({"group": k, "aggregated": final_state}), {"group_by": True}
                
        # Returns a pending generator inside a new DataTree
        return DataTree(_group_gen())

    def col(self, **kwargs) -> List[Any]:
        """Collect values from the stream based on registered paths."""
        collected = []
        def _collect_op(record, metadata):
            return [record.get_leaves(metadata['register'][k]) for k in kwargs.keys()], {}
        collected.append([k for k in kwargs.keys()])
        for record, _ in yield_branches(self, _register(**kwargs), _collect_op):
            collected.append(record)
        return collected
        
        

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
    print(tree.head(n=2).col(name = "name", age = "age"))
    print(tree.group_by("age"))
if __name__ == "__main__":
    __main__()