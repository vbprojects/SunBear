from typing import Any, Union, List, Callable, Dict, Tuple, Set, Optional

class Path:
    """Handles path resolution for multidimensional access."""
    
    @staticmethod
    def parse_depth(path: Union[str, Tuple[str, ...]]) -> Tuple[str, ...]:
        """Parses depth traversal (tuple or dot-notation)."""
        if isinstance(path, str):
            return tuple(path.split('.'))
        if isinstance(path, tuple):
            return path
        raise TypeError("Depth traversal path must be a string or tuple of strings")
        
    @staticmethod
    def parse_breadth(path: List[str]) -> List[str]:
        """Parses breadth projection (list of strings)."""
        if isinstance(path, list):
            return path
        raise TypeError("Breadth projection path must be a list of strings")

class SchemaType:
    pass

class NullType(SchemaType):
    def __eq__(self, other):
        return isinstance(other, NullType)
    
    def __hash__(self):
        return hash(None)
        
    def __repr__(self):
        return "Null"

class PrimitiveType(SchemaType):
    def __init__(self, type_class: type):
        self.type_class = type_class
        
    def __eq__(self, other):
        if not isinstance(other, PrimitiveType):
            return False
        return self.type_class == other.type_class
        
    def __hash__(self):
        return hash(self.type_class)
        
    def __repr__(self):
        return self.type_class.__name__

class UnionType(SchemaType):
    def __init__(self, types: Set[SchemaType]):
        # Unpack nested unions
        flat_types = set()
        for t in types:
            if isinstance(t, UnionType):
                flat_types.update(t.types)
            else:
                flat_types.add(t)
        self.types = frozenset(flat_types)
        
    def __eq__(self, other):
        if not isinstance(other, UnionType):
            return False
        return self.types == other.types
        
    def __hash__(self):
        return hash(self.types)
        
    def __repr__(self):
        return f"Union[{', '.join(repr(t) for t in self.types)}]"

class ListType(SchemaType):
    def __init__(self, item_schema: Union[SchemaType, 'Branch']):
        self.item_schema = item_schema
        
    def __eq__(self, other):
        if not isinstance(other, ListType):
            return False
        return self.item_schema == other.item_schema
        
    def __hash__(self):
        # Hash is tricky for mutable Branches, fallback to id if unhashable
        try:
            return hash(self.item_schema)
        except TypeError:
            return id(self.item_schema)
        
    def __repr__(self):
        return f"List[{repr(self.item_schema)}]"

class FunctionType(SchemaType):
    def __init__(self, func: Callable):
        self.func = func
        
    def __eq__(self, other):
        if not isinstance(other, FunctionType):
            return False
        return self.func == other.func
        
    def __hash__(self):
        return hash(self.func)
        
    def __repr__(self):
        return f"Func[{self.func.__name__}]"

# Thunk for deferred function logical operations
class ThunkFunctionType(SchemaType):
    def __init__(self, func_a: Callable, func_b: Callable, operator: str):
        self.func_a = func_a
        self.func_b = func_b
        self.operator = operator # 'or', 'and'
        
        if operator == 'or':
            self.func = lambda x: func_a(x) or func_b(x)
        elif operator == 'and':
            self.func = lambda x: func_a(x) and func_b(x)
        else:
            raise ValueError(f"Unknown operator {operator}")

    def __eq__(self, other):
        if not isinstance(other, ThunkFunctionType):
            return False
        return self.func_a == other.func_a and self.func_b == other.func_b and self.operator == other.operator

    def __hash__(self):
        return hash((self.func_a, self.func_b, self.operator))

    def __repr__(self):
        return f"Thunk[{self.func_a.__name__} {self.operator} {self.func_b.__name__}]"

def combine_types(a: SchemaType, b: SchemaType) -> SchemaType:
    if a == b:
        return a
    
    # Custom function union via thunk
    if isinstance(a, FunctionType) and isinstance(b, FunctionType):
        return ThunkFunctionType(a.func, b.func, 'or')
    elif isinstance(a, FunctionType) and isinstance(b, ThunkFunctionType):
        return ThunkFunctionType(a.func, b.func, 'or')
    elif isinstance(a, ThunkFunctionType) and isinstance(b, FunctionType):
        return ThunkFunctionType(a.func, b.func, 'or')
    
    # Standard union
    types = set()
    for t in (a, b):
        if isinstance(t, UnionType):
            types.update(t.types)
        else:
            types.add(t)
    return UnionType(types)

class Node:
    pass

class Leaf(Node):
    def __init__(self, schema_type: SchemaType):
        self.type = schema_type
        
    def __eq__(self, other):
        if not isinstance(other, Leaf):
            return False
        return True # Leaves are type invariant according to spec, handled via combine_types externally
        
    def __repr__(self):
        return repr(self.type)

class Branch(Node):
    def __init__(self, fields: Dict[str, Node]):
        self.fields = fields
        
    def __eq__(self, other):
        if not isinstance(other, Branch):
            return False
            
        # "a = (b=int, c=str) == a=(c=str, b=int, d=int) # False"
        # However, "a = (b=int, c=str) == a=(b=int) -> True"
        # Meaning: If one branch is a SUBSET of another, it's equivalent. 
        # But wait, if they have different unrelated fields, it's False.
        # Let's say: Is a subset of b OR b is a subset of a.
        keys_self = set(self.fields.keys())
        keys_other = set(other.fields.keys())
        
        if keys_self.issubset(keys_other) or keys_other.issubset(keys_self):
            # Check overlap fields equivalence
            overlap = keys_self.intersection(keys_other)
            for k in overlap:
                if self.fields[k] != other.fields[k]:
                    return False
            return True
            
        return False
        
    def reconcile(self, other: 'Branch') -> 'Branch':
        """Creates a union of two Branches based on maximizing type representation and preserving Null invariants."""
        if not self == other:
            raise ValueError("Cannot natively reconcile non-equivalent branches (non-subset relationships).")
        
        all_keys = set(self.fields.keys()).union(other.fields.keys())
        new_fields = {}
        for k in all_keys:
            if k in self.fields and k in other.fields:
                s_node = self.fields[k]
                o_node = other.fields[k]
                if isinstance(s_node, Branch) and isinstance(o_node, Branch):
                    new_fields[k] = s_node.reconcile(o_node)
                elif isinstance(s_node, Leaf) and isinstance(o_node, Leaf):
                    new_fields[k] = Leaf(combine_types(s_node.type, o_node.type))
                else:
                    raise ValueError(f"Mismatch Branch vs Leaf at '{k}'")
            elif k in self.fields:
                # Other is missing field, essentially Null
                node = self.fields[k]
                if isinstance(node, Leaf):
                    new_fields[k] = Leaf(combine_types(node.type, NullType()))
                else:
                    new_fields[k] = node
            else:
                node = other.fields[k]
                if isinstance(node, Leaf):
                    new_fields[k] = Leaf(combine_types(node.type, NullType()))
                else:
                    new_fields[k] = node
        return Branch(new_fields)
        
    def diff(self, other: 'Branch') -> 'Branch':
        """
        Takes another schema Branch and returns a new schema (Branch) containing
        only the paths that are different. The types at those paths are combined.
        """
        diff_fields = {}
        all_keys = set(self.fields.keys()) | set(other.fields.keys())
        
        for k in all_keys:
            in_self = k in self.fields
            in_other = k in other.fields
            
            if in_self and not in_other:
                # difference: missing in other
                diff_fields[k] = self.fields[k]
            elif in_other and not in_self:
                # difference: missing in self
                diff_fields[k] = other.fields[k]
            else:
                # in both
                s_node = self.fields[k]
                o_node = other.fields[k]
                
                # Leaf.__eq__ always returns True (subset semantics), so compare types directly
                if isinstance(s_node, Leaf) and isinstance(o_node, Leaf):
                    if s_node.type != o_node.type:
                        diff_fields[k] = Leaf(combine_types(s_node.type, o_node.type))
                elif isinstance(s_node, Branch) and isinstance(o_node, Branch):
                    # Branch.__eq__ uses subset semantics, so always recurse to find child diffs
                    child_diff = s_node.diff(o_node)
                    if child_diff.fields:
                        diff_fields[k] = child_diff
                elif s_node != o_node:
                    # Mismatched node types (Branch vs Leaf)
                    if isinstance(s_node, Leaf):
                        diff_fields[k] = Leaf(combine_types(s_node.type, DictType()))
                    else:
                        diff_fields[k] = Leaf(combine_types(DictType(), o_node.type))
                            
        return Branch(diff_fields)

    def _tree_str(self, level=0, root_name="Root"):
        lines = []
        indent = "    " * level
        lines.append(f"{indent}{root_name}")
        for k, v in self.fields.items():
            if isinstance(v, Branch):
                lines.append(v._tree_str(level + 1, f"- {k}"))
            elif isinstance(v, Leaf):
                lines.append(f"{indent}    - {k} : {v.type}")
        return "\n".join(lines)

    def __str__(self):
        return self._tree_str()

    def _repr_html_(self, name="Root", collapsed=False):
        open_attr = "" if collapsed else " open"
        html = f"<details{open_attr}><summary><b>{name}</b></summary><ul style='list-style-type:none; padding-left: 20px; margin: 0;'>"
        for k, v in self.fields.items():
            if isinstance(v, Branch):
                html += f"<li>{v._repr_html_(k, collapsed)}</li>"
            elif isinstance(v, Leaf):
                html += f"<li><span><b>{k}</b> : {v.type}</span></li>"
        html += "</ul></details>"
        return html

    def show(self, collapsed=False):
        try:
            __IPYTHON__
            from IPython.display import display, HTML
            display(HTML(self._repr_html_(collapsed=collapsed)))
        except NameError:
            print(str(self))

    def __repr__(self):
        return f"({', '.join(f'{k}={repr(v)}' for k, v in self.fields.items())})"

    def add(self, path: Union[str, Tuple[str, ...]], schema_type: SchemaType) -> 'Branch':
        parsed_path = Path.parse_depth(path)
        if not parsed_path:
            return self
            
        current_key = parsed_path[0]
        new_fields = dict(self.fields)
        
        if len(parsed_path) == 1:
            if current_key in new_fields:
                node = new_fields[current_key]
                if isinstance(node, Leaf):
                    new_fields[current_key] = Leaf(combine_types(node.type, schema_type))
                else:
                    raise ValueError(f"Cannot add type to a Branch node at '{current_key}'")
            else:
                new_fields[current_key] = Leaf(schema_type)
        else:
            if current_key in new_fields:
                node = new_fields[current_key]
                if isinstance(node, Branch):
                    new_fields[current_key] = node.add(parsed_path[1:], schema_type)
                else:
                    raise ValueError(f"Expected Branch at '{current_key}' but found Leaf")
            else:
                # Create intermediate branch
                new_fields[current_key] = Branch({}).add(parsed_path[1:], schema_type)
                
        return Branch(new_fields)

    def delete(self, path: Union[str, Tuple[str, ...]], schema_type: SchemaType = None) -> 'Branch':
        parsed_path = Path.parse_depth(path)
        if not parsed_path:
            return self
            
        current_key = parsed_path[0]
        if current_key not in self.fields:
            return self
            
        new_fields = dict(self.fields)
        
        if len(parsed_path) == 1:
            if schema_type is None:
                del new_fields[current_key]
            else:
                node = new_fields[current_key]
                if isinstance(node, Leaf):
                    # Check if node type matches or is union containing the type
                    if node.type == schema_type:
                        new_fields[current_key] = Leaf(NullType())
                    elif isinstance(node.type, UnionType) and schema_type in node.type.types:
                        remaining = set(node.type.types) - {schema_type}
                        if len(remaining) == 1:
                            new_fields[current_key] = Leaf(list(remaining)[0])
                        elif len(remaining) == 0:
                            new_fields[current_key] = Leaf(NullType())
                        else:
                            new_fields[current_key] = Leaf(UnionType(remaining))
                else:
                    raise ValueError(f"Cannot delete type from a Branch node at '{current_key}'")
        else:
            node = new_fields[current_key]
            if isinstance(node, Branch):
                updated_branch = node.delete(parsed_path[1:], schema_type)
                if not updated_branch.fields:
                    del new_fields[current_key]
                else:
                    new_fields[current_key] = updated_branch
            else:
                raise ValueError(f"Expected Branch at '{current_key}' but found Leaf")
                
        return Branch(new_fields)

    def move(self, source_path: Union[str, Tuple[str, ...]], dest_path: Union[str, Tuple[str, ...]]) -> 'Branch':
        s_path = Path.parse_depth(source_path)
        d_path = Path.parse_depth(dest_path)
        
        # 1. Extract node
        def get_node(branch, path):
            if not path:
                return branch
            k = path[0]
            if k not in branch.fields:
                raise KeyError(f"Path not found: {source_path}")
            if len(path) == 1:
                return branch.fields[k]
            node = branch.fields[k]
            if not isinstance(node, Branch):
                raise ValueError(f"Expected Branch at '{k}' but found Leaf")
            return get_node(node, path[1:])
            
        target_node = get_node(self, s_path)
        
        # 2. Delete source
        after_delete = self.delete(s_path) # deletes the whole node
        
        # 3. Insert node at dest_path
        def set_node(branch, path, n):
            k = path[0]
            nf = dict(branch.fields)
            if len(path) == 1:
                nf[k] = n
            else:
                if k in nf:
                    child = nf[k]
                    if not isinstance(child, Branch):
                        raise ValueError(f"Expected Branch at '{k}'")
                    nf[k] = set_node(child, path[1:], n)
                else:
                    nf[k] = set_node(Branch({}), path[1:], n)
            return Branch(nf)
            
        return set_node(after_delete, d_path, target_node)

class Schema(Branch):
    """
    A named tuple tree that describes the shape of the data. 
    May be an Inferred Schema (truth) or Projection Schema (view).
    """
    def __init__(self, fields: Dict[str, Node], is_projection: bool = False):
        super().__init__(fields)
        self.is_projection = is_projection
        
    def apply_projection(self, projection_schema: 'Schema') -> 'Schema':
        # Used to enforce localized view
        pass

def schema_diff(schema1: 'Branch', schema2: 'Branch') -> 'Branch':
    """
    Takes 2 schema Branch nodes and returns a new schema with only the paths
    that are different.
    """
    return schema1.diff(schema2)

def infer_schema(obj: Any) -> Node:
    if obj is None:
        return Leaf(NullType())
    if isinstance(obj, dict):
        fields = {}
        for k, v in obj.items():
            fields[k] = infer_schema(v)
        return Branch(fields)
    if isinstance(obj, list):
        if not obj:
            return Leaf(ListType(NullType()))
        # combine types of all elements
        item_schema = infer_schema(obj[0])
        for item in obj[1:]:
            s = infer_schema(item)
            # Reconcile if branch, combine if leaf
            if isinstance(item_schema, Branch) and isinstance(s, Branch):
                if item_schema == s:
                    item_schema = item_schema.reconcile(s)
            elif isinstance(item_schema, Leaf) and isinstance(s, Leaf):
                item_schema = Leaf(combine_types(item_schema.type, s.type))
                
        if isinstance(item_schema, Branch):
            return Leaf(ListType(item_schema))
        else:
            return Leaf(ListType(item_schema.type))
            
    return Leaf(PrimitiveType(type(obj)))
