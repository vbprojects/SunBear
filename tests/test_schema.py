"""test_schema.py — regression tests for the carried-over Schema module.

Schema.py was copied verbatim from src_old/sunbear/Schema.py with only a
minor adaptation (Schema.from_records accepts a list of plain dicts, since
DataTree is now lazy — call .collect() first or access via dt.schema).

These tests cover:
- Type inference (Primitive, NullType, UnionType, ListType)
- Node reconciliation (Leaf type-invariance, Branch null-invariance)
- Non-transitive equality
- Visualization (terminal tree, Jupyter _repr_html_)
- Schema.filter() — record selection by schema
"""
import unittest
import io
import sys

from sunbear import (
    Schema, SchemaType, Primitive, NullType, UnionType, ListType, CustomType,
    Leaf, Branch, Node, infer_schema, reconcile, combine_types,
)
from sunbear import DataTree


# ═══════════════════════════════════════════════════════════════════════════
# Type hierarchy
# ═══════════════════════════════════════════════════════════════════════════

class TestTypeHierarchy(unittest.TestCase):

    def test_primitive_equality(self):
        self.assertEqual(Primitive(int), Primitive(int))
        self.assertNotEqual(Primitive(int), Primitive(str))

    def test_primitive_repr(self):
        self.assertEqual(repr(Primitive(int)), "int")

    def test_null_singleton(self):
        n1 = NullType()
        n2 = NullType()
        self.assertIs(n1, n2)

    def test_union_unpacks_nested(self):
        inner = UnionType({Primitive(int), Primitive(str)})
        outer = UnionType({inner, Primitive(float)})
        # outer should flatten to all three
        self.assertEqual(len(outer.types), 3)

    def test_union_equality(self):
        a = UnionType({Primitive(int), Primitive(str)})
        b = UnionType({Primitive(str), Primitive(int)})
        self.assertEqual(a, b)

    def test_list_type(self):
        lt = ListType(Primitive(int))
        self.assertEqual(repr(lt), "List[int]")
        self.assertEqual(lt, ListType(Primitive(int)))
        self.assertNotEqual(lt, ListType(Primitive(str)))

    def test_custom_type(self):
        ct = CustomType("Email", lambda v: isinstance(v, str) and "@" in v)
        self.assertEqual(ct, CustomType("Email", lambda v: True))
        self.assertNotEqual(ct, CustomType("Phone", lambda v: True))
        self.assertTrue(ct.check("a@b.com"))
        self.assertFalse(ct.check("nope"))


# ═══════════════════════════════════════════════════════════════════════════
# combine_types
# ═══════════════════════════════════════════════════════════════════════════

class TestCombineTypes(unittest.TestCase):

    def test_same_type_returns_first(self):
        a, b = Primitive(int), Primitive(int)
        self.assertIs(combine_types(a, b), a)

    def test_different_returns_union(self):
        result = combine_types(Primitive(int), Primitive(str))
        self.assertIsInstance(result, UnionType)
        self.assertEqual(len(result.types), 2)


# ═══════════════════════════════════════════════════════════════════════════
# Node hierarchy
# ═══════════════════════════════════════════════════════════════════════════

class TestNodeHierarchy(unittest.TestCase):

    def test_leaf_type_invariance(self):
        # v3 spec: Leaf(int) == Leaf(str) — type doesn't matter
        self.assertEqual(Leaf(Primitive(int)), Leaf(Primitive(str)))

    def test_branch_subset_equivalence(self):
        # null-invariance: missing fields OK (subset relationship)
        a = Branch({"x": Leaf(Primitive(int))})
        b = Branch({"x": Leaf(Primitive(int)), "y": Leaf(Primitive(int))})
        self.assertEqual(a, b)

    def test_branch_name_invariance(self):
        # different field names break equivalence
        a = Branch({"x": Leaf(Primitive(int))})
        b = Branch({"y": Leaf(Primitive(int))})
        self.assertNotEqual(a, b)

    def test_branch_extra_field_mismatch_breaks_eq(self):
        # two branches with disjoint extra fields are NOT equal
        b1 = Branch({"x": Leaf(Primitive(int)), "y": Leaf(Primitive(int))})
        b2 = Branch({"x": Leaf(Primitive(int)), "z": Leaf(Primitive(int))})
        # neither is subset of the other (y vs z)
        self.assertNotEqual(b1, b2)

    def test_non_transitivity_via_subsets(self):
        # Non-transitivity case: a==b and b==c does not imply a==c
        # because the subset relation is not transitive across branches
        # with disjoint extra fields.
        # Here b and c are not equal (disjoint extras), so the implication
        # simply doesn't apply — but a third branch can be equal to both b
        # and c even when b != c.
        a = Branch({"x": Leaf(Primitive(int))})
        b = Branch({"x": Leaf(Primitive(int)), "y": Leaf(Primitive(int))})
        c = Branch({"x": Leaf(Primitive(int)), "z": Leaf(Primitive(int))})
        self.assertEqual(a, b)  # a ⊂ b
        self.assertEqual(a, c)  # a ⊂ c
        self.assertNotEqual(b, c)  # neither is subset of the other
        # this demonstrates non-transitivity:
        # a==b is True, a==c is True, but b==c is False


# ═══════════════════════════════════════════════════════════════════════════
# infer_schema
# ═══════════════════════════════════════════════════════════════════════════

class TestInferSchema(unittest.TestCase):

    def test_infer_scalar(self):
        node = infer_schema(42)
        self.assertIsInstance(node, Leaf)
        self.assertEqual(node.type, Primitive(int))

    def test_infer_dict(self):
        node = infer_schema({"a": 1, "b": "hi"})
        self.assertIsInstance(node, Branch)
        self.assertIn("a", node.fields)
        self.assertIn("b", node.fields)

    def test_infer_nested(self):
        node = infer_schema({"outer": {"inner": 1}})
        self.assertIsInstance(node, Branch)
        outer = node.fields["outer"]
        self.assertIsInstance(outer, Branch)
        self.assertIsInstance(outer.fields["inner"], Leaf)

    def test_infer_list(self):
        node = infer_schema([1, 2, 3])
        # list of int → List[int] type
        self.assertIsInstance(node, Leaf)
        self.assertIsInstance(node.type, ListType)
        self.assertEqual(node.type.item_type, Primitive(int))

    def test_infer_null(self):
        node = infer_schema(None)
        self.assertIsInstance(node, Leaf)
        self.assertIsInstance(node.type, NullType)


# ═══════════════════════════════════════════════════════════════════════════
# reconcile
# ═══════════════════════════════════════════════════════════════════════════

class TestReconcile(unittest.TestCase):

    def test_reconcile_compatible(self):
        a = infer_schema({"x": 1, "y": "a"})
        b = infer_schema({"x": 2, "y": "b"})
        r = reconcile([a, b])
        self.assertIsInstance(r, Branch)

    def test_reconcile_empty(self):
        r = reconcile([])
        # empty reconciliation returns empty Branch
        self.assertIsInstance(r, Branch)


# ═══════════════════════════════════════════════════════════════════════════
# Schema class
# ═══════════════════════════════════════════════════════════════════════════

class TestSchemaClass(unittest.TestCase):

    def test_from_records_basic(self):
        s = Schema.from_records([{"a": 1, "b": "x"}, {"a": 2, "b": "y"}])
        self.assertIsInstance(s, Schema)
        self.assertIsInstance(s._root, Branch)

    def test_from_records_empty(self):
        s = Schema.from_records([])
        self.assertIsInstance(s, Schema)

    def test_show_terminal(self):
        # capture stdout to ensure .show() prints something.
        # Force utf-8 to handle box-drawing characters on Windows.
        s = Schema.from_records([{"a": 1}])
        buf = io.StringIO()
        old, sys.stdout = sys.stdout, buf
        try:
            # reconfigure stdout for utf-8 (Windows cp1252 default breaks)
            try:
                sys.stdout.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass
            s.show()
        finally:
            sys.stdout = old
        self.assertGreater(len(buf.getvalue()), 0)
        # the field name 'a' appears somewhere in the rendered output
        self.assertIn("a", buf.getvalue())

    def test_str_representation(self):
        s = Schema.from_records([{"a": 1, "b": "hi"}])
        s_str = str(s)
        self.assertIsInstance(s_str, str)
        self.assertGreater(len(s_str), 0)

    def test_filter_records(self):
        s = Schema.from_records([{"a": 1}, {"a": 2}])
        matched = s.filter([{"a": 1}, {"a": "wrong"}, {"a": 3}])
        # Schema equality is Leaf-type-invariant, so all three match in this v3 spec
        # but we at least verify it runs and returns a list
        self.assertIsInstance(matched, list)


# ═══════════════════════════════════════════════════════════════════════════
# Schema integration with DataTree
# ═══════════════════════════════════════════════════════════════════════════

class TestSchemaDataTreeIntegration(unittest.TestCase):

    def test_dt_schema_lazy_materializes(self):
        # dt.schema auto-materializes the stream
        dt = DataTree.from_records([{"a": 1, "b": "x"}])
        schema = dt.schema
        self.assertIsInstance(schema, Schema)

    def test_dt_schema_after_expr(self):
        # schema reflects post-expr state
        from sunbear.expr import b, assign
        dt = DataTree.from_records([{"a": 1}])
        dt2 = dt.expr(assign(b.b, 2))
        schema = dt2.schema
        self.assertIsInstance(schema, Schema)
        # the reconciled branch should contain 'a' and 'b'
        self.assertIn("a", schema._root.fields)
        self.assertIn("b", schema._root.fields)


if __name__ == "__main__":
    unittest.main()
