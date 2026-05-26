# Implements DataTree, a tree structure for parsing json records.
from typing import List, Dict, Any, Union, Tuple, Callable
from .Schema import Path, Schema, Branch, Leaf, infer_schema
import warnings

class DataTree:
    @classmethod
    def register_method(cls, func: Callable) -> Callable:
        """Decorator to register a method to DataTree."""
        setattr(cls, func.__name__, func)
        return func

    @classmethod
    def load_extensions(cls, module) -> None:
        """Load and register all public functions from a module as methods."""
        import inspect
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if not name.startswith('_'):
                setattr(cls, name, func)

    def __init__(self, records: Union[List[Dict[str, Any]], 'Iterable[Dict[str, Any]]'] = None, defer_evaluation: bool = False):
        self.records = records if records is not None else []
        self._schemas: Dict[int, Schema] = {}  
        self._record_schema_map: List[int] = [] 
        self._reconciled = True
        self.stale = False
        
        # Tombstones only make sense if records is materialized as a list
        self._tombstones = [False] * len(self.records) if isinstance(self.records, (list, tuple)) else []

        if not defer_evaluation and self.records is not None:
            self.build_schemas()

    def schemas(self, materialize: bool = True) -> Dict[int, Schema]:
        if materialize and (self.stale or not self._schemas):
            self.build_schemas()
        return self._schemas

    @property
    def mat(self):
        """Gives materialized view of the DataTree, triggering GC if needed."""
        if self.stale or not self._schemas:
            self.build_schemas()
        return self
    
    def build_schemas(self):
        """Builds schemas dynamically by scanning through records."""
        # Materialize records if it's an iterator so we don't consume and lose it
        if not isinstance(self.records, (list, tuple)):
            self.records = list(self.records)

        # GC tombstones
        if any(self._tombstones) if hasattr(self, '_tombstones') and self._tombstones else False:
            alive_records = []
            for i, dead in enumerate(self._tombstones):
                if not dead:
                    alive_records.append(self.records[i])
            self.records = alive_records
            self._tombstones = [False] * len(self.records)
            
        self._schemas.clear()
        self._record_schema_map.clear()
        
        next_id = 0
        self._reconciled = True
        
        for rec in self.records:
            s_node = infer_schema(rec)
            if not isinstance(s_node, Branch):
                raise ValueError("Records must be dictionary objects")
            s = Schema(s_node.fields)
            
            matched_ids = []
            for sid, existing_schema in self._schemas.items():
                if existing_schema == s: 
                    # They are subset equivalents, perform reconciliation
                    self._schemas[sid] = Schema(existing_schema.reconcile(s).fields)
                    matched_ids.append(sid)
            
            if len(matched_ids) > 0:
                if len(matched_ids) > 1:
                    self._reconciled = False
                    warnings.warn("Multiple overlapping non-transitive schemas detected. Reconcile to enforce single structure.")
                # For now just map to all matched schemas or the first one, per spec "records can be part of multiple schemas"
                # But our map currently expects a single int or needs to be a list of ints.
                # Let's map it to the first matched one to keep map size 1 per record for simplicity, or change it to support multiple.
                self._record_schema_map.append(matched_ids[0])
            else:
                self._schemas[next_id] = s
                self._record_schema_map.append(next_id)
                next_id += 1
                
        self.stale = False
        return self

    def __len__(self):
        """Materializing call to fetch length after sweeping GC."""
        if self.stale or not self._schemas:
            self.build_schemas()
        if not isinstance(self.records, (list, tuple)):
            self.records = list(self.records)
        return len(self.records)

    def length(self):
        return len(self)

    def shallow(self, func: Callable):
        from .DataBranch import DataBranch
        return DataBranch(self).shallow(func)

    def deep(self, func: Callable):
        from .DataBranch import DataBranch
        return DataBranch(self).deep(func)

    def isna(self):
        from .DataBranch import DataBranch
        return DataBranch(self).isna()

    def not_(self, func: Callable):
        from .DataBranch import DataBranch
        return DataBranch(self).not_(func)

    def assign(self, val: Any):
        from .DataBranch import DataBranch
        return DataBranch(self).assign(val)

    def __str__(self):
        if self.stale or not self._schemas:
            self.build_schemas()
        if not isinstance(self.records, (list, tuple)):
            self.records = list(self.records)
        lines = [f"DataTree with {len(self.records)} records and {len(self._schemas)} Schemas:"]
        for sid, s in self._schemas.items():
            lines.append(f"Schema {sid}:")
            lines.append(str(s))
        return "\n".join(lines)

    def _repr_html_(self, collapsed=False):
        if self.stale or not self._schemas:
            self.build_schemas()
        if not isinstance(self.records, (list, tuple)):
            self.records = list(self.records)
        html = f"<div><b>DataTree</b> ({len(self.records)} records, {len(self._schemas)} Schemas)</div>"
        for sid, s in self._schemas.items():
            html += f"<div style='margin-left: 20px;'>{s._repr_html_(name=f'Schema {sid}', collapsed=collapsed)}</div>"
        return html

    def show(self, collapsed=False):
        try:
            __IPYTHON__
            from IPython.display import display, HTML
            display(HTML(self._repr_html_(collapsed=collapsed)))
        except NameError:
            print(str(self))

    def __getitem__(self, item: Tuple[Any, Any]):
        from .DataBranch import DataBranch
        return DataBranch(self)[item]
