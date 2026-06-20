"""Schema.py — type-level schema trees for sunbearv3.

Schemas are named tuples representing the structure of records.
They are trees where nodes are names and leaves are types.

Key semantics (from schema_notes.md):
- Leaves are TYPE-INVARIANT: Leaf(int) == Leaf(str) is True
- Schemas are NULL-INVARIANT: missing fields are equivalent to None
- Schemas are NOT name-invariant: different field names break equivalence
- Non-transitive: A==B and B==C does not imply A==C
"""

from __future__ import annotations
from typing import (
    Any, Callable, Dict, FrozenSet, List, Optional, Set, Tuple,
)

# ═══════════════════════════════════════════════════════════════════════════
# SchemaType hierarchy — leaf value types
# ═══════════════════════════════════════════════════════════════════════════

class SchemaType:
    """Abstract base for leaf-level type descriptors."""
    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        raise NotImplementedError

    def __hash__(self) -> int:
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError


class Primitive(SchemaType):
    """Wraps a Python type like int, str, float, bool."""
    __slots__ = ('_type',)

    def __init__(self, python_type: type) -> None:
        self._type = python_type

    @property
    def type(self) -> type:
        return self._type

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Primitive):
            return False
        return self._type is other._type

    def __hash__(self) -> int:
        return hash(self._type)

    def __repr__(self) -> str:
        return self._type.__name__


class NullType(SchemaType):
    """Singleton sentinel for None / missing values."""
    _inst: Optional[NullType] = None
    __slots__ = ()

    def __new__(cls) -> NullType:
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __eq__(self, other: object) -> bool:
        return isinstance(other, NullType)

    def __hash__(self) -> int:
        return hash(None)

    def __repr__(self) -> str:
        return "Null"


class UnionType(SchemaType):
    """A union of schema types. Auto-unpacks nested Unions."""
    __slots__ = ('_types',)

    def __init__(self, types: Set[SchemaType]) -> None:
        flat: Set[SchemaType] = set()
        for t in types:
            if isinstance(t, UnionType):
                flat.update(t._types)
            else:
                flat.add(t)
        self._types: FrozenSet[SchemaType] = frozenset(flat)

    @property
    def types(self) -> FrozenSet[SchemaType]:
        return self._types

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, UnionType):
            return False
        return self._types == other._types

    def __hash__(self) -> int:
        return hash(self._types)

    def __repr__(self) -> str:
        inner = ", ".join(repr(t) for t in sorted(self._types, key=repr))
        return f"Union[{inner}]"


class ListType(SchemaType):
    """A list/array with an item type."""
    __slots__ = ('_item_type',)

    def __init__(self, item_type: SchemaType) -> None:
        self._item_type = item_type

    @property
    def item_type(self) -> SchemaType:
        return self._item_type

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ListType):
            return False
        return self._item_type == other._item_type

    def __hash__(self) -> int:
        return hash(('List', self._item_type))

    def __repr__(self) -> str:
        return f"List[{self._item_type!r}]"


class CustomType(SchemaType):
    """A named custom type with a membership predicate."""
    __slots__ = ('_name', '_predicate')

    def __init__(self, name: str, predicate: Callable[[Any], bool]) -> None:
        self._name = name
        self._predicate = predicate

    @property
    def name(self) -> str:
        return self._name

    @property
    def predicate(self) -> Callable[[Any], bool]:
        return self._predicate

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, CustomType):
            return False
        return self._name == other._name

    def __hash__(self) -> int:
        return hash(('Custom', self._name))

    def __repr__(self) -> str:
        return self._name

    def check(self, value: Any) -> bool:
        """Test whether a value satisfies this custom type's predicate."""
        return self._predicate(value)


# ═══════════════════════════════════════════════════════════════════════════
# Utility
# ═══════════════════════════════════════════════════════════════════════════

def combine_types(a: SchemaType, b: SchemaType) -> SchemaType:
    """Combine two SchemaTypes. If equal, return a; otherwise return Union."""
    if a == b:
        return a
    types: Set[SchemaType] = set()
    for t in (a, b):
        if isinstance(t, UnionType):
            types.update(t._types)
        else:
            types.add(t)
    return UnionType(types)


# ═══════════════════════════════════════════════════════════════════════════
# Node hierarchy — the schema tree
# ═══════════════════════════════════════════════════════════════════════════

class Node:
    """Abstract base for schema tree nodes (Leaf or Branch)."""
    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        raise NotImplementedError

    def __hash__(self) -> int:
        raise NotImplementedError

    def __repr__(self) -> str:
        raise NotImplementedError

    # -- visualization --

    def _tree_lines(self) -> List[str]:
        """Return list of plain-text lines for terminal display."""
        raise NotImplementedError

    def _repr_html_(self) -> str:
        """Return collapsible HTML for Jupyter (IPython protocol)."""
        return self._repr_html_impl()

    def _repr_html_impl(self, collapsed: bool = False) -> str:
        raise NotImplementedError

    def show(self, collapsed: bool = False) -> None:
        """Display schema: auto-detect IPython or fall back to print."""
        try:
            __IPYTHON__  # type: ignore[name-defined]
            from IPython.display import display, HTML
            display(HTML(self._repr_html_impl(collapsed=collapsed)))
        except (NameError, ImportError):
            print(str(self))


class Leaf(Node):
    """Terminal node holding a SchemaType.

    KEY SEMANTIC: Leaves are TYPE-INVARIANT.
    Leaf(Primitive(int)) == Leaf(Primitive(str)) is True.
    """
    __slots__ = ('type',)

    def __init__(self, schema_type: SchemaType) -> None:
        self.type = schema_type

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Leaf):
            return False
        return True  # TYPE-INVARIANT: all leaves are equivalent

    def __hash__(self) -> int:
        return 0  # All leaves hash the same

    def __repr__(self) -> str:
        return repr(self.type)

    def _tree_lines(self) -> List[str]:
        return [repr(self.type)]

    def _repr_html_impl(self, collapsed: bool = False) -> str:
        return f"<span>{self.type!r}</span>"


class Branch(Node):
    """Named container with Dict[str, Node] children.

    Equivalence:
    - Two branches are equivalent if one's field-name set is a SUBSET
      of the other's, AND all overlapping fields have equivalent children.
    - This encodes:
      * NULL-INVARIANCE: missing fields are OK (subset relationship)
      * NAME-INVARIANCE: different field names break equivalence
      * TYPE-INVARIANCE: inherited from Leaf.__eq__
    """
    __slots__ = ('fields',)

    def __init__(self, fields: Dict[str, Node]) -> None:
        self.fields = fields

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Branch):
            return False

        keys_self = set(self.fields.keys())
        keys_other = set(other.fields.keys())

        # Must have subset relationship (null-invariant)
        if not (keys_self.issubset(keys_other) or keys_other.issubset(keys_self)):
            return False

        # Overlapping fields must have equivalent children
        overlap = keys_self.intersection(keys_other)
        for k in overlap:
            if self.fields[k] != other.fields[k]:
                return False
        return True

    def __hash__(self) -> int:
        # Non-transitive equivalence means we can't have a perfect hash
        # that is consistent with __eq__. Return a constant.
        return 0

    def __repr__(self) -> str:
        inner = ", ".join(f"{k}={v!r}" for k, v in self.fields.items())
        return f"({inner})"

    def __str__(self) -> str:
        return "\n".join(self._tree_lines())

    # -- reconciliation --

    def reconcile_with(self, other: Branch) -> Branch:
        """Pairwise reconciliation: merge two equivalent branches into one
        that represents the maximum of both (widening types as needed)."""
        if not (self == other):
            raise ValueError(
                "Cannot reconcile non-equivalent branches "
                "(no subset relationship between field name sets)"
            )
        return _reconcile_pair(self, other)

    # -- tree visualization --

    def _tree_lines(self) -> List[str]:
        """Build Unicode box-drawing tree for terminal display."""
        if not self.fields:
            return ["Root"]
        lines: List[str] = ["Root"]
        self._build_tree_lines(lines, "", True)
        return lines

    def _build_tree_lines(
        self, lines: List[str], prefix: str, is_root: bool
    ) -> None:
        """Recursively build tree lines with proper indentation."""
        if not self.fields:
            if not is_root:
                lines.append(f"{prefix}└── (empty)")
            return

        names = list(self.fields.keys())
        for i, name in enumerate(names):
            is_last = (i == len(names) - 1)
            connector = "└── " if is_last else "├── "
            child = self.fields[name]

            if isinstance(child, Leaf):
                lines.append(f"{prefix}{connector}{name} : {child.type!r}")
            elif isinstance(child, Branch):
                lines.append(f"{prefix}{connector}{name}")
                child_prefix = prefix + ("    " if is_last else "│   ")
                child._build_tree_lines(lines, child_prefix, False)

    def _repr_html_impl(self, collapsed: bool = False) -> str:
        """Build collapsible HTML tree for Jupyter."""
        open_attr = "" if collapsed else " open"
        if not self.fields:
            return (
                f"<details{open_attr}>"
                f"<summary><b>Root</b></summary>"
                f"<span style='color:#888'>(empty)</span>"
                f"</details>"
            )

        html = (
            f"<details{open_attr}>"
            f"<summary><b>Root</b></summary>"
            f"<ul style='list-style-type:none; padding-left: 20px; margin: 0;'>"
        )
        for name, child in self.fields.items():
            html += self._child_html(name, child, collapsed)
        html += "</ul></details>"
        return html

    def _child_html(self, name: str, child: Node, collapsed: bool) -> str:
        """Render a single child node as HTML."""
        if isinstance(child, Leaf):
            return f"<li><span><b>{name}</b> : {child.type!r}</span></li>"
        elif isinstance(child, Branch):
            open_attr = "" if collapsed else " open"
            inner = (
                f"<details{open_attr}>"
                f"<summary><b>{name}</b></summary>"
                f"<ul style='list-style-type:none; padding-left: 20px; margin: 0;'>"
            )
            for cname, cchild in child.fields.items():
                inner += child._child_html(cname, cchild, collapsed)
            inner += "</ul></details>"
            return f"<li>{inner}</li>"
        return ""

    # -- type statistics --

    def type_stats(self, records: List[dict]) -> Dict[str, Dict[str, float]]:
        """Compute per-leaf type ratios (including None/missing) across records.

        Returns a dict mapping dotted paths to {type_name: ratio} dicts.
        """
        total = len(records)
        if total == 0:
            return {}

        counts: Dict[str, Dict[str, int]] = {}
        for rec in records:
            self._collect_type_stats(rec, "", counts)

        ratios: Dict[str, Dict[str, float]] = {}
        for path, cnts in counts.items():
            ratios[path] = {
                t: c / total for t, c in sorted(cnts.items())
            }
        return ratios

    def _collect_type_stats(
        self,
        obj: Any,
        prefix: str,
        stats: Dict[str, Dict[str, int]],
    ) -> None:
        """Recursively collect type counts for a single record."""
        for name, child in self.fields.items():
            path = f"{prefix}.{name}" if prefix else name
            value = obj.get(name) if isinstance(obj, dict) else None

            if isinstance(child, Leaf):
                stats.setdefault(path, {})
                if value is None:
                    stats[path]["Null"] = stats[path].get("Null", 0) + 1
                elif isinstance(child.type, UnionType):
                    matched = False
                    for t in child.type.types:
                        if isinstance(t, Primitive) and isinstance(value, t.type):
                            stats[path][repr(t)] = stats[path].get(repr(t), 0) + 1
                            matched = True
                            break
                    if not matched:
                        tname = type(value).__name__
                        stats[path][tname] = stats[path].get(tname, 0) + 1
                else:
                    tname = repr(child.type)
                    stats[path][tname] = stats[path].get(tname, 0) + 1
            elif isinstance(child, Branch):
                if isinstance(value, dict):
                    child._collect_type_stats(value, path, stats)
                else:
                    stats.setdefault(path, {})
                    stats[path]["missing"] = stats[path].get("missing", 0) + 1


# ═══════════════════════════════════════════════════════════════════════════
# Reconciliation
# ═══════════════════════════════════════════════════════════════════════════

def _reconcile_pair(a: Branch, b: Branch) -> Branch:
    """Reconcile two equivalent branches into one."""
    all_keys = set(a.fields.keys()) | set(b.fields.keys())
    new_fields: Dict[str, Node] = {}

    for k in all_keys:
        in_a = k in a.fields
        in_b = k in b.fields

        if in_a and in_b:
            child_a = a.fields[k]
            child_b = b.fields[k]
            if isinstance(child_a, Branch) and isinstance(child_b, Branch):
                new_fields[k] = _reconcile_pair(child_a, child_b)
            elif isinstance(child_a, Leaf) and isinstance(child_b, Leaf):
                new_fields[k] = Leaf(combine_types(child_a.type, child_b.type))
            else:
                raise ValueError(
                    f"Mismatch: Branch vs Leaf at '{k}'. "
                    f"Got {type(child_a).__name__} and {type(child_b).__name__}"
                )
        elif in_a:
            # Present in a, missing in b → widen to Union[type, Null]
            child = a.fields[k]
            if isinstance(child, Leaf):
                new_fields[k] = Leaf(combine_types(child.type, NullType()))
            else:
                new_fields[k] = child
        else:
            # Present in b, missing in a → widen to Union[type, Null]
            child = b.fields[k]
            if isinstance(child, Leaf):
                new_fields[k] = Leaf(combine_types(child.type, NullType()))
            else:
                new_fields[k] = child

    return Branch(new_fields)


def reconcile(branches: List[Branch]) -> Branch:
    """Reconcile a list of pairwise-equivalent branches into a single
    minimum tree that re-establishes transitivity."""
    if not branches:
        return Branch({})
    if len(branches) == 1:
        return branches[0]

    result = branches[0]
    for b in branches[1:]:
        result = _reconcile_pair(result, b)
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Schema inference
# ═══════════════════════════════════════════════════════════════════════════

def infer_schema(obj: Any) -> Node:
    """Infer a schema tree from a Python object.

    - None → Leaf(NullType())
    - dict → Branch({k: infer_schema(v) for k, v in obj.items()})
    - list → Leaf(ListType(inferred_item_type))
    - anything else → Leaf(Primitive(type(obj)))
    """
    if obj is None:
        return Leaf(NullType())

    if isinstance(obj, dict):
        fields = {k: infer_schema(v) for k, v in obj.items()}
        return Branch(fields)

    if isinstance(obj, list):
        if not obj:
            return Leaf(ListType(NullType()))
        item_type = _infer_list_item_type(obj)
        return Leaf(ListType(item_type))

    return Leaf(Primitive(type(obj)))


def _infer_list_item_type(items: list) -> SchemaType:
    """Infer the item type for a list, combining types of all elements."""
    if not items:
        return NullType()

    first = infer_schema(items[0])
    if isinstance(first, Leaf):
        result_type: SchemaType = first.type
    elif isinstance(first, Branch):
        return first  # Let caller wrap in ListType
    else:
        return NullType()

    for item in items[1:]:
        s = infer_schema(item)
        if isinstance(s, Leaf) and isinstance(result_type, SchemaType):
            result_type = combine_types(result_type, s.type)
        elif isinstance(s, Branch):
            # Mixed: scalar and dict in list — merge into union
            result_type = combine_types(
                result_type,
                CustomType("dict", lambda x: isinstance(x, dict)),
            )
        # If s is Branch and result_type is already Branch, skip
        # (the Branch is returned directly by caller)

    return result_type


# ═══════════════════════════════════════════════════════════════════════════
# Schema class — high-level interface
# ═══════════════════════════════════════════════════════════════════════════

class Schema:
    """High-level schema interface wrapping a root Branch.

    Provides inference from records, reconciliation, filtering,
    and rich visualization.
    """
    __slots__ = ('_root', '_name')

    def __init__(self, root: Branch, name: Optional[str] = None) -> None:
        self._root = root
        self._name = name

    @property
    def root(self) -> Branch:
        return self._root

    @property
    def name(self) -> Optional[str]:
        return self._name

    @classmethod
    def from_record(cls, record: dict) -> Schema:
        """Infer schema from a single record dict."""
        node = infer_schema(record)
        if not isinstance(node, Branch):
            raise ValueError("Top-level schema must be a Branch (dict)")
        return cls(node)

    @classmethod
    def from_records(cls, records: List[dict]) -> Schema:
        """Infer and reconcile schema from multiple records."""
        if not records:
            return cls(Branch({}))

        branches: List[Branch] = []
        for rec in records:
            node = infer_schema(rec)
            if not isinstance(node, Branch):
                raise ValueError("Top-level schema must be a Branch (dict)")
            branches.append(node)

        reconciled = reconcile(branches)
        return cls(reconciled)

    def filter(self, records: List[dict]) -> List[dict]:
        """Return only records that structurally match this schema.

        A record matches if its inferred schema is equivalent to this one.
        """
        return [
            rec for rec in records
            if self._root == infer_schema(rec)
        ]

    # -- delegation to root Branch --

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Schema):
            return False
        return self._root == other._root

    def __hash__(self) -> int:
        return hash(self._root)

    def __repr__(self) -> str:
        return f"Schema({self._root!r})"

    def __str__(self) -> str:
        if self._name:
            # Replace "Root" with the schema name in the tree display
            root_str = str(self._root)
            if root_str.startswith("Root"):
                return f"{self._name}{root_str[4:]}"
            return f"{self._name}{chr(10)}{root_str}"
        return str(self._root)

    def _repr_html_(self) -> str:
        return self._repr_html_impl()

    def _repr_html_impl(self, collapsed: bool = False) -> str:
        if self._name:
            html = self._root._repr_html_impl(collapsed=collapsed)
            return html.replace("<b>Root</b>", f"<b>{self._name}</b>")
        return self._root._repr_html_impl(collapsed=collapsed)

    def show(self, collapsed: bool = False) -> None:
        """Display schema: auto-detect IPython or fall back to print."""
        try:
            __IPYTHON__  # type: ignore[name-defined]
            from IPython.display import display, HTML
            display(HTML(self._repr_html_impl(collapsed=collapsed)))
        except (NameError, ImportError):
            print(str(self))

    @staticmethod
    def show_list(schemas: List[Schema], collapsed: bool = False) -> None:
        """Pretty-print a list of unreconcilable schemas."""
        try:
            __IPYTHON__  # type: ignore[name-defined]
            from IPython.display import display, HTML
            html = "<div style='border: 1px solid #ccc; padding: 10px;'>"
            html += "<h3>Unreconcilable Schemas</h3>"
            for s in schemas:
                html += s._repr_html_impl(collapsed=collapsed)
            html += "</div>"
            display(HTML(html))
        except (NameError, ImportError):
            print("Unreconcilable Schemas:")
            for s in schemas:
                print("-" * 20)
                print(str(s))

    def type_stats(self, records: List[dict]) -> Dict[str, Dict[str, float]]:
        return self._root.type_stats(records)

class SchemaList:
    """Container for multiple unreconcilable schemas."""
    __slots__ = ('schemas',)

    def __init__(self, schemas: List[Schema]) -> None:
        self.schemas = schemas

    def show(self, collapsed: bool = False) -> None:
        Schema.show_list(self.schemas, collapsed=collapsed)
    def __repr__(self) -> str:
        return f"SchemaList({self.schemas!r})"
    def _repr_html_(self):
        return self.show(collapsed=True)
    def __getitem__(self, index):
        return self.schemas[index]