from typing import Callable, Any, Optional, List
from .Schema import Schema, Path
from .utils import isna

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
        
    @staticmethod
    def _resolve_path(val, path_segments):
        for i, p in enumerate(path_segments):
            if isinstance(val, dict):
                val = val.get(p, None)
            elif isinstance(val, list):
                remaining = path_segments[i:]
                return [DataBranch._resolve_path(item, remaining) for item in val]
            else:
                return None
        return val
        
    def _apply_projection(self, records, col_idx):
        if isinstance(col_idx, list):
            parsed_cols = []
            for c in col_idx:
                if isinstance(c, tuple): parsed_cols.append(c)
                elif isinstance(c, str): parsed_cols.append(Path.parse_depth(c))
            for r in records:
                row_proj = []
                for depth_path in parsed_cols:
                    row_proj.append(DataBranch._resolve_path(r, list(depth_path)))
                yield row_proj
        else:
            depth_path = Path.parse_depth(col_idx)
            for r in records:
                yield DataBranch._resolve_path(r, list(depth_path))

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
        col_idx = getattr(self, 'projection_col', None)
        
        def op(records):
            import copy
            
            # Since records could be a generator, we create a parallel generator for projection 
            # or just calculate it row-by-row
            parsed_cols = []
            if col_idx is not None:
                if isinstance(col_idx, list):
                    for c in col_idx:
                        if isinstance(c, tuple): parsed_cols.append(c)
                        elif isinstance(c, str): parsed_cols.append(Path.parse_depth(c))
                else:
                    parsed_cols.append(Path.parse_depth(col_idx))
                    
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
                    projected_val = r
                    
                test_val = func(projected_val)
                if isinstance(test_val, bool):
                    if test_val:
                        yield r
                else:
                    if col_idx is None:
                        yield test_val
                        continue
                    new_r = copy.deepcopy(r)
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
                    yield new_r
                    
        branch = DataBranch(self, operation=op)
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
                
        def op(records):
            for item in records:
                yield _walk(item)
            
        branch = DataBranch(self, operation=op)
        branch.projection_col = self.projection_col
        return branch

    def isna(self) -> 'DataBranch':
        return self.shallow(isna)

    def not_(self, func_or_branch: Callable) -> 'DataBranch':
        def negate_func(x):
            return not func_or_branch(x)
        return self.shallow(negate_func)

    def assign(self, val: Any) -> 'DataBranch':
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
                
            for r in records:
                new_r = copy.deepcopy(r)
                if col_idx is not None:
                    for depth_path in parsed_cols:
                        curr = new_r
                        for p in depth_path[:-1]:
                            if p not in curr or not isinstance(curr[p], dict):
                                curr[p] = {}
                            curr = curr[p]
                        curr[depth_path[-1]] = val
                yield new_r
            
        branch = DataBranch(self, operation=op)
        branch.projection_col = col_idx
        branch.return_tree = True 
        return branch

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

        def op(records):
            import copy
            for r in records:
                result = {}
                for depth_path in parsed:
                    val = DataBranch._resolve_path(r, list(depth_path))
                    result[depth_path[-1]] = copy.deepcopy(val)
                yield result

        branch = DataBranch(self, operation=op)
        branch.return_tree = True
        return branch

from .DataTree import DataTree
DataTree.register_method(DataBranch.add_path)
DataTree.register_method(DataBranch.aggregate)
DataTree.register_method(DataBranch.group_by)
DataTree.register_method(DataBranch.path)
DataBranch.register_method(DataBranch.add_path)
DataBranch.register_method(DataBranch.aggregate)
DataBranch.register_method(DataBranch.group_by)
DataBranch.register_method(DataBranch.path)
