from typing import Callable, Any, Optional, List
from .Schema import Schema, Path
from .utils import isna, resolve_path, col


class DataBranch:
    @classmethod
    def register_method(cls, func: Callable) -> Callable:
        """Decorator to register a method to DataBranch."""
        setattr(cls, func.__name__, func)
        return func

    @classmethod
    def load_extensions(cls, module) -> None:
        """Load and register all public functions from a module as methods."""
        import inspect
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith('_'):
                setattr(cls, name, func)

    def __init__(self, source: Any, operation: Optional[Callable] = None, projection_schema: Optional[Schema] = None):
        """Create a new DataBranch — a lazy view over a DataTree or another DataBranch.

        Parameters
        ----------
        source : DataTree or DataBranch
            The upstream data source this branch wraps.
        operation : callable or None
            A lazy transformation applied on evaluation. Receives an iterable of records.
        projection_schema : Schema or None
            Optional schema hint for the branch output.
        """
        self.source = source
        self.operation = operation
        self.projection_schema = projection_schema
        self.projection_col = None
        self.return_tree = False

    def evaluate_records(self):
        if hasattr(self.source, 'stale') and getattr(self.source, 'stale', False):
            self.source.build_schemas()
            
        if hasattr(self.source, 'evaluate_records'):
            records = self.source.evaluate_records()
        elif hasattr(self.source, 'records'):
            records = self.source.records
        else:
            records = self.source

        if self.operation:
            records = self.operation(records)
            
        return records

    def map_records(self, func: Callable, copy: bool = True) -> 'DataBranch':
        """Atomic primitive: translates one record to another."""
        def op(records):
            import copy as pycopy
            for r in records:
                val = pycopy.deepcopy(r) if copy else r
                yield func(val)
        branch = DataBranch(self, operation=op)
        branch.return_tree = True
        return branch

    def copy(self) -> 'DataBranch':
        """Yields a deep copy of each record passing through the branch."""
        return self.map_records(lambda x: x, copy=True)

    def filter_records(self, func: Callable) -> 'DataBranch':
        """Atomic primitive: filters records where func returns True."""
        def op(records):
            for r in records:
                if func(r):
                    yield r
        branch = DataBranch(self, operation=op)
        branch.projection_col = self.projection_col
        branch.return_tree = self.return_tree
        return branch

    def flat_map_records(self, func: Callable, copy: bool = True) -> 'DataBranch':
        """Atomic primitive: drops one record and yields multiple (flattening)."""
        def op(records):
            import copy as pycopy
            for r in records:
                val = pycopy.deepcopy(r) if copy else r
                for item in func(val):
                    yield item
        branch = DataBranch(self, operation=op)
        return branch

    def head(self, n: int = 5) -> 'DataBranch':
        """Yields the first n records."""
        def op(records):
            import itertools
            return itertools.islice(records, n)
        
        branch = DataBranch(self, operation=op)
        branch.projection_col = self.projection_col
        branch.return_tree = self.return_tree
        return branch

    def tail(self, n: int = 5) -> 'DataBranch':
        """Yields the last n records."""
        def op(records):
            import collections
            return iter(collections.deque(records, maxlen=n))
        
        branch = DataBranch(self, operation=op)
        branch.projection_col = self.projection_col
        branch.return_tree = self.return_tree
        return branch

    def _apply_projection(self, records, col_idx):
        if isinstance(col_idx, list):
            parsed_cols = []
            for c in col_idx:
                if isinstance(c, tuple): parsed_cols.append(c)
                elif isinstance(c, str): parsed_cols.append(Path.parse_depth(c))
            for r in records:
                row_proj = []
                for depth_path in parsed_cols:
                    row_proj.append(resolve_path(r, list(depth_path)))
                yield row_proj
        else:
            depth_path = Path.parse_depth(col_idx)
            for r in records:
                yield resolve_path(r, list(depth_path))

    def schemas(self, materialize: bool = True):
        if not materialize and self.projection_schema:
            return {0: self.projection_schema}
            
        if materialize:
            records = self.evaluate_records()
            # If the branch strictly preserves dictionary outputs or is specified as a tree 
            if self.return_tree or getattr(self, 'projection_col', None) is None:
                from .DataTree import DataTree
                temp_tree = DataTree(records, defer_evaluation=False)
                return temp_tree.schemas(materialize=False)
            
            # Branches that result purely in mapped arrays might not strictly have physical schemas to return
            return {}
            
        # Defer fall-through
        if hasattr(self.source, 'schemas'):
            return self.source.schemas(materialize=False)
        return {}
            
    def collect(self) -> Any:
        """Evaluate the branch DAG and produce the final result.

        Returns
        -------
        DataTree or list
            - If ``return_tree=True`` (set by ``.path()``, ``.assign()``, etc.), returns a
              ``DataTree`` wrapping the evaluated records.
            - If a projection column is set (via ``[:, col]``), returns a list of projected values.
            - Otherwise returns a list of records.
        """
        records = self.evaluate_records()
        
        if self.return_tree:
            from .DataTree import DataTree
            return DataTree(records, defer_evaluation=True)
            
        col_idx = getattr(self, 'projection_col', None)
        if col_idx is not None:
            return list(self._apply_projection(records, col_idx))
            
        # Return as list if it's an iterator/generator
        if hasattr(records, '__iter__') and not hasattr(records, '__len__'):
            return list(records)
        return records

    def materialize(self):
        """Evaluate the branch and return a DataTree built from the current state."""
        from .DataTree import DataTree
        records = self.collect()

        if isinstance(records, DataTree):
            return records.mat

        if hasattr(records, '__iter__') and not isinstance(records, (list, tuple)):
            records = list(records)

        return DataTree(records, defer_evaluation=True)

    def __len__(self):
        return len(self.collect())

    def length(self):
        return len(self)

    def shallow(self, func: Callable) -> 'DataBranch':
        """Apply a function to the projected value of each record.

        - If ``func`` returns ``bool``: acts as a filter (keep/discard the record).
        - If ``func`` returns a non-bool: acts as a mutation (replaces the projected value).

        Parameters
        ----------
        func : callable
            Receives the projected value (or full record if no projection is set).

        Returns
        -------
        DataBranch
        """
        col_idx = getattr(self, 'projection_col', None)
        parsed_cols = []
        if col_idx is not None:
            if isinstance(col_idx, list):
                for c in col_idx:
                    if isinstance(c, tuple): parsed_cols.append(c)
                    elif isinstance(c, str): parsed_cols.append(Path.parse_depth(c))
            else:
                parsed_cols.append(Path.parse_depth(col_idx))
                
        def row_mapper(r):
            if col_idx is not None:
                if isinstance(col_idx, list):
                    projected_val = [resolve_path(r, list(dp)) for dp in parsed_cols]
                else:
                    projected_val = resolve_path(r, list(parsed_cols[0]))
            else:
                projected_val = r
                
            test_val = func(projected_val)
            if isinstance(test_val, bool):
                if test_val:
                    return [r]
                else:
                    return []
            else:
                if col_idx is None:
                    return [test_val]
                
                new_r = r
                if isinstance(col_idx, list):
                    for j, depth_path in enumerate(parsed_cols):
                        curr = new_r
                        for p in depth_path[:-1]:
                            if p not in curr or not isinstance(curr[p], dict): curr[p] = {}
                            curr = curr[p]
                        curr[depth_path[-1]] = test_val[j]
                else:
                    depth_path = parsed_cols[0]
                    curr = new_r
                    for p in depth_path[:-1]:
                        if p not in curr or not isinstance(curr[p], dict): curr[p] = {}
                        curr = curr[p]
                    curr[depth_path[-1]] = test_val
                return [new_r]

        branch = self.flat_map_records(row_mapper, copy=True)
        branch.projection_col = col_idx
        return branch

    def deep(self, func: Callable) -> 'DataBranch':
        def _walk(obj):
            if isinstance(obj, dict):
                return {k: _walk(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [_walk(v) for v in obj]
            else:
                val = func(obj)
                return val if not isinstance(val, bool) else (obj if val else None)
                
        def row_mapper(r):
            return _walk(r)
            
        branch = self.map_records(row_mapper, copy=False)
        branch.projection_col = self.projection_col
        return branch

    def isna(self) -> 'DataBranch':
        return self.shallow(isna)

    def not_(self, func_or_branch: Callable) -> 'DataBranch':
        def negate_func(x):
            return not func_or_branch(x)
        return self.shallow(negate_func)

    def explode(self) -> 'DataBranch':
        """Explodes the first matched projecting column that contains a list."""
        col_idx = getattr(self, 'projection_col', None)
        if col_idx is None or not isinstance(col_idx, list):
            raise TypeError("explode() requires a breadth projection with at least 2 columns")

        col_names = []
        for c in col_idx:
            if isinstance(c, str):
                col_names.append((c, None))
            elif isinstance(c, tuple):
                col_names.append((c[-1], c))
            else:
                col_names.append((None, c))

        def row_flattener(r):
            if isinstance(r, dict):
                exploded_key = None
                for name, _ in col_names:
                    val = r.get(name) if name else None
                    if isinstance(val, list):
                        exploded_key = name
                        break
                if exploded_key is None:
                    return [r]

                items = r[exploded_key]
                if not items:
                    return []
                
                # yield one copy of row per item
                res = []
                import copy
                for item in items:
                    row = copy.deepcopy(r)
                    row[exploded_key] = item
                    res.append(row)
                return res

            elif isinstance(r, (list, tuple)):
                exploded_idx = None
                for i in range(len(r)):
                    if isinstance(r[i], list):
                        exploded_idx = i
                        break
                if exploded_idx is None:
                    return [r]

                items = r[exploded_idx]
                if not items:
                    return []

                res = []
                import copy
                for item in items:
                    row = copy.deepcopy(r)
                    row[exploded_idx] = item
                    res.append(row)
                return res
            else:
                return [r]

        branch = self.flat_map_records(row_flattener, copy=False)
        branch.return_tree = True
        return branch

    def _build_mapper(self, target_path, expr):
        """Automatically generates a row_mapper function."""
        from .utils import resolve_path, set_path

        def auto_mapper(record):
            import copy
            # 1. Evaluate the expression
            if hasattr(expr, 'evaluate'):
                val = expr.evaluate(record)
            else:
                val = expr
                
            # 2. Assign it to the target path safely
            new_record = copy.deepcopy(record) if isinstance(record, dict) else record
            if isinstance(new_record, dict):
                set_path(new_record, target_path.split('.'), val)
            return new_record
            
        return auto_mapper

    def assign(self, expr: Any = None, **kwargs) -> 'DataBranch':
        col_idx = getattr(self, 'projection_col', None)
        
        # Case A: Using the syntax `db[:, k].assign(v)`
        if expr is not None and col_idx is not None:
            # We assume single string path or single dimension for clarity right now. 
            # In a more complete implementation, we'd handle tuples and lists of col_idx.
            target_path = col_idx if isinstance(col_idx, str) else str(col_idx)
            auto_mapper = self._build_mapper(target_path, expr)
            branch = self.map_records(auto_mapper, copy=False)
            branch.projection_col = None # Clear context after assignment
            branch.return_tree = True 
            return branch

        # Case B: Standard syntax `db.assign(k=v)` or no projection_col
        db = self
        if expr is not None and not kwargs:
             raise ValueError("Must specify kwargs if expr is provided but projection_col is not set.")
             
        for k, v in kwargs.items():
            auto_mapper = db._build_mapper(k, v)
            db = db.map_records(auto_mapper, copy=False)
            db.return_tree = True
        return db

    def add_path(self, dest: str, source_branch: 'DataBranch') -> 'DataBranch':
        def op(records):
            import copy
            source_records = source_branch.evaluate_records()
            col_idx = getattr(source_branch, 'projection_col', None)
            if col_idx is not None:
                source_records = source_branch._apply_projection(source_records, col_idx)
                
            for r, src_val in zip(records, source_records):
                new_r = copy.deepcopy(r)
                if dest == "..":
                    yield {src_val: new_r}
                else:
                    parsed = Path.parse_depth(dest)
                    curr = new_r
                    for p in parsed[:-1]:
                        if p not in curr or not isinstance(curr[p], dict):
                            curr[p] = {}
                        curr = curr[p]
                    curr[parsed[-1]] = src_val
                    yield new_r
                    
        branch = DataBranch(self, operation=op)
        branch.return_tree = True
        return branch

    def aggregate(self) -> 'DataBranch':
        col_idx = getattr(self, 'projection_col', None)
        
        def op(records):
            import copy
            parsed_cols = []
            if col_idx is not None:
                if isinstance(col_idx, list):
                    for c in col_idx:
                        if isinstance(c, tuple): parsed_cols.append(c)
                        elif isinstance(c, str): parsed_cols.append(Path.parse_depth(c))
                else:
                    parsed_cols.append(Path.parse_depth(col_idx))
            
            # For aggregate, we group ALL valid records under the path name.
            # Unaggregated records (where the projection is None) remain unaltered.
            aggregated_items = []
            unaggregated = []
            
            for r in records:
                if col_idx is not None:
                    if isinstance(col_idx, list):
                        projected_val = []
                        for depth_path in parsed_cols:
                            val = r
                            for p in depth_path:
                                if isinstance(val, dict): val = val.get(p, None)
                                else: val = None; break
                            projected_val.append(val)
                    else:
                        depth_path = parsed_cols[0]
                        val = r
                        for p in depth_path:
                            if isinstance(val, dict): val = val.get(p, None)
                            else: val = None; break
                        projected_val = val
                else:
                    projected_val = None
                    
                if projected_val is None or (isinstance(projected_val, list) and all(v is None for v in projected_val)):
                    unaggregated.append(copy.deepcopy(r))
                else:
                    aggregated_items.append(copy.deepcopy(projected_val))
            
            if aggregated_items:
                if col_idx is not None and not isinstance(col_idx, list):
                    # We output a single dictionary with the grouped items under the path's root
                    res = {}
                    curr = res
                    for p in depth_path[:-1]:
                        curr[p] = {}
                        curr = curr[p]
                    curr[depth_path[-1]] = aggregated_items
                    yield res
                else:
                    # If multiple columns or no columns, just generic group
                    yield {"aggregated": aggregated_items}
                
            for r in unaggregated:
                yield r
                
        branch = DataBranch(self, operation=op)
        branch.return_tree = True
        return branch

    def group_by(self, target_node="members") -> 'DataBranch':
        col_idx = getattr(self, 'projection_col', None)
        
        def op(records):
            import copy
            from collections import defaultdict
            
            parsed_cols = []
            if col_idx is not None:
                if isinstance(col_idx, list):
                    for c in col_idx:
                        if isinstance(c, tuple): parsed_cols.append(c)
                        elif isinstance(c, str): parsed_cols.append(Path.parse_depth(c))
                else:
                    parsed_cols.append(Path.parse_depth(col_idx))
                    
            def _get_val(root_val, path):
                val = root_val
                for p in path:
                    if isinstance(val, dict): 
                        val = val.get(p, None)
                    elif isinstance(val, list):
                        val = [_get_val(v, [p]) for v in val]
                    else: 
                        val = None; break
                return val

            def _group_array(arr, path, target_node):
                groups = defaultdict(list)
                disp_key = path[-1] if path else "group"
                
                for r in arr:
                    val = _get_val(r, path) if path else r
                    key = tuple(val) if isinstance(val, list) else val
                    try:
                        _ = hash(key)
                        groups[key].append(copy.deepcopy(r))
                    except TypeError:
                        groups[str(key)].append(copy.deepcopy(r))
                        
                res = []
                for key, members in groups.items():
                    k_disp = list(key) if isinstance(key, tuple) else key
                    res.append({disp_key: k_disp, target_node: members})
                return res

            def _map_group(r, path, disp_key, target_node):
                if not path:
                    return r
                if isinstance(r, dict):
                    p = path[0]
                    if p not in r:
                        return r
                    val = r[p]
                    if isinstance(val, list):
                        new_r = r.copy()
                        new_r[p] = _group_array(val, path[1:], target_node)
                        return new_r
                    else:
                        new_r = r.copy()
                        new_r[p] = _map_group(val, path[1:], disp_key, target_node)
                        return new_r
                return r
            
            if col_idx is None:
                yield {"group": None, target_node: list(records)}
                return

            if isinstance(col_idx, list):
                groups = defaultdict(list)
                for r in records:
                    projected_val = []
                    for depth_path in parsed_cols:
                        projected_val.append(_get_val(r, depth_path))
                    projected_val = [tuple(v) if isinstance(v, list) else v for v in projected_val]
                    key = tuple(projected_val)
                    try:
                        _ = hash(key)
                        groups[key].append(copy.deepcopy(r))
                    except TypeError:
                        groups[str(key)].append(copy.deepcopy(r))
                for key, members in groups.items():
                    res = {target_node: members}
                    for i, k in enumerate(key):
                        res[parsed_cols[i][-1]] = k
                    yield res
                return
            
            depth_path = parsed_cols[0]
            disp_key = depth_path[-1]
            
            hits_list_checked = False
            hits_list = False
            groups = defaultdict(list)
            
            for r in records:
                if not hits_list_checked:
                    val = r
                    for p in depth_path:
                        if isinstance(val, dict):
                            val = val.get(p, None)
                        elif isinstance(val, list):
                            hits_list = True
                            break
                        else:
                            break
                    if hits_list or val is not None:
                        hits_list_checked = True

                if hits_list:
                    yield _map_group(r, depth_path, disp_key, target_node)
                else:
                    val = _get_val(r, depth_path)
                    key = tuple(val) if isinstance(val, list) else val
                    try:
                        _ = hash(key)
                        groups[key].append(copy.deepcopy(r))
                    except TypeError:
                        groups[str(key)].append(copy.deepcopy(r))
            
            if not hits_list:
                for key, members in groups.items():
                    k_disp = list(key) if isinstance(key, tuple) else key
                    yield {disp_key: k_disp, target_node: members}

        branch = DataBranch(self, operation=op)
        branch.return_tree = True
        return branch

    def __getitem__(self, item: Any) -> 'DataBranch':
        row_idx = None
        col_idx = None
        
        if isinstance(item, tuple):
            if len(item) == 2: row_idx, col_idx = item
            else: raise KeyError("DataTree expects 2D indexing at most: [records, fields]")
        else:
            row_idx = item

        if isinstance(col_idx, slice) and col_idx == slice(None, None, None):
            col_idx = None
            
        def selection_operation(records):
            if records is None: return None
            
            if isinstance(row_idx, slice):
                if isinstance(records, (list, tuple)):
                    start, stop, step = row_idx.indices(len(records))
                    return [records[i] for i in range(start, stop, step)]
                else:
                    import itertools
                    # For iterators, only positive slicing works
                    return itertools.islice(records, row_idx.start, row_idx.stop, row_idx.step)
            elif isinstance(row_idx, int):
                if isinstance(records, (list, tuple)):
                    return [records[row_idx]]
                else:
                    import itertools
                    return [next(itertools.islice(records, row_idx, row_idx + 1))]
            elif isinstance(row_idx, list) and all(isinstance(i, int) for i in row_idx):
                if isinstance(records, (list, tuple)):
                    return [records[i] for i in row_idx]
                else:
                    # Inefficient for iterators but strictly possible if monotonically increasing
                    records = list(records)
                    return [records[i] for i in row_idx]
            elif isinstance(row_idx, dict):
                def _prune(rec, schema):
                    pruned = {}
                    for k, v in schema.items():
                        val = rec.get(k) if isinstance(rec, dict) else None
                        if isinstance(v, dict):
                            pruned[k] = _prune(val, v)
                        else:
                            pruned[k] = val
                    return pruned

                def filter_gen(iterator):
                    for r in iterator:
                        yield _prune(r, row_idx)
                
                return filter_gen(records)
            else:
                return records

        branch = DataBranch(self, operation=selection_operation)
        branch.projection_col = col_idx if col_idx is not None else getattr(self, 'projection_col', None)
        return branch

    def __str__(self):
        if self.projection_schema:
            return f"DataBranch Projection:\n{self.projection_schema}"
        else:
            return f"DataBranch inferred from source DataTree:\n{self.source}"

    def _repr_html_(self, collapsed=False):
        if self.projection_schema:
            return f"<div><b>DataBranch Projection</b></div><div style='margin-left: 20px;'>{self.projection_schema._repr_html_(collapsed=collapsed)}</div>"
        else:
            if hasattr(self.source, '_repr_html_'):
                return f"<div><b>DataBranch (Lazy)</b> inferred from source:</div><div style='margin-left: 20px;'>{self.source._repr_html_(collapsed=collapsed)}</div>"
            return f"<div><b>DataBranch (Lazy)</b></div>"

    def show(self, collapsed=False):
        try:
            __IPYTHON__
            from IPython.display import display, HTML
            display(HTML(self._repr_html_(collapsed=collapsed)))
        except NameError:
            print(str(self))

    def path(self, paths: 'Union[str, List[str], List[Tuple[str, ...]], Tuple[str, ...]]') -> 'DataBranch':
        """Resolve one or more paths, returning a DataBranch that yields dicts
        keyed by the final segment of each path.  Sets return_tree=True so
        .collect() produces a DataTree ready for further chaining.

        Parameters
        ----------
        paths : str | tuple[str,…] | list[str] | list[tuple[str,…]]
            Depth paths (dot-string or tuple) or breadth list of field names.

        Returns
        -------
        DataBranch with return_tree=True.
        """
        if isinstance(paths, (str, tuple)):
            paths = [paths]

        parsed = []
        for p in paths:
            if isinstance(p, str):
                parsed.append(Path.parse_depth(p))
            elif isinstance(p, tuple):
                parsed.append(p)

        def row_mapper(r):
            result = {}
            for depth_path in parsed:
                val = resolve_path(r, list(depth_path))
                result[depth_path[-1]] = val
            return result

        branch = self.map_records(row_mapper, copy=True)
        branch.return_tree = True
        return branch

from .DataTree import DataTree
DataTree.register_method(DataBranch.add_path)
DataTree.register_method(DataBranch.aggregate)
DataTree.register_method(DataBranch.group_by)
DataTree.register_method(DataBranch.path)
DataTree.register_method(DataBranch.explode)
DataBranch.register_method(DataBranch.add_path)
DataBranch.register_method(DataBranch.aggregate)
DataBranch.register_method(DataBranch.group_by)
DataBranch.register_method(DataBranch.path)
DataBranch.register_method(DataBranch.explode)
