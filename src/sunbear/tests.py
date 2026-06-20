"""tests.py — unit tests for sunbearv3 Schema module."""

import unittest
from Schema import (
    SchemaType,
    Primitive,
    NullType,
    UnionType,
    ListType,
    CustomType,
    Leaf,
    Branch,
    Node,
    Schema,
    infer_schema,
    reconcile,
    combine_types,
)
from DataTree import DataTree


class TestSchemaTypes(unittest.TestCase):
    """Tests for the SchemaType hierarchy."""

    def test_primitive_equality(self):
        self.assertEqual(Primitive(int), Primitive(int))
        self.assertNotEqual(Primitive(int), Primitive(str))
        self.assertNotEqual(Primitive(int), Primitive(float))

    def test_null_singleton(self):
        n1 = NullType()
        n2 = NullType()
        self.assertIs(n1, n2)
        self.assertEqual(n1, n2)
        self.assertNotEqual(NullType(), Primitive(int))

    def test_union_flattening(self):
        u1 = UnionType({Primitive(int), Primitive(str)})
        u2 = UnionType({Primitive(str), Primitive(int)})
        self.assertEqual(u1, u2)

        # Nested unions should flatten
        inner = UnionType({Primitive(int), Primitive(float)})
        outer = UnionType({inner, Primitive(str)})
        self.assertEqual(len(outer.types), 3)
        self.assertIn(Primitive(int), outer.types)
        self.assertIn(Primitive(float), outer.types)
        self.assertIn(Primitive(str), outer.types)

    def test_list_equality(self):
        self.assertEqual(
            ListType(Primitive(int)),
            ListType(Primitive(int)),
        )
        self.assertNotEqual(
            ListType(Primitive(int)),
            ListType(Primitive(str)),
        )

    def test_custom_type(self):
        is_positive = CustomType("PositiveInt", lambda x: isinstance(x, int) and x > 0)
        is_positive2 = CustomType("PositiveInt", lambda x: x > 0)
        # Same name → equal (predicates can't be compared)
        self.assertEqual(is_positive, is_positive2)
        self.assertNotEqual(is_positive, CustomType("NegativeInt", lambda x: x < 0))

        self.assertTrue(is_positive.check(5))
        self.assertFalse(is_positive.check(-3))
        self.assertFalse(is_positive.check("hi"))

    def test_combine_types(self):
        # Same type → returns the type
        result = combine_types(Primitive(int), Primitive(int))
        self.assertEqual(result, Primitive(int))

        # Different types → Union
        result = combine_types(Primitive(int), Primitive(str))
        self.assertIsInstance(result, UnionType)
        self.assertEqual(len(result.types), 2)

        # Union + type → wider Union
        u = UnionType({Primitive(int), Primitive(str)})
        result = combine_types(u, Primitive(float))
        self.assertIsInstance(result, UnionType)
        self.assertEqual(len(result.types), 3)

    def test_repr(self):
        self.assertEqual(repr(Primitive(int)), "int")
        self.assertEqual(repr(NullType()), "Null")
        self.assertEqual(repr(ListType(Primitive(str))), "List[str]")
        self.assertIn("int", repr(UnionType({Primitive(int), Primitive(str)})))
        self.assertIn("str", repr(UnionType({Primitive(int), Primitive(str)})))


class TestLeaf(unittest.TestCase):
    """Tests for Leaf — the type-invariant terminal node."""

    def test_type_invariance(self):
        """KEY SEMANTIC: Leaf(int) == Leaf(str) is True."""
        self.assertEqual(
            Leaf(Primitive(int)),
            Leaf(Primitive(str)),
        )
        self.assertEqual(
            Leaf(Primitive(int)),
            Leaf(NullType()),
        )
        self.assertEqual(
            Leaf(Primitive(int)),
            Leaf(ListType(Primitive(str))),
        )

    def test_all_leaves_hash_same(self):
        """All leaves must hash identically for dict/set membership."""
        self.assertEqual(
            hash(Leaf(Primitive(int))),
            hash(Leaf(Primitive(str))),
        )
        self.assertEqual(
            hash(Leaf(Primitive(int))),
            hash(Leaf(NullType())),
        )

    def test_leaf_not_equal_to_non_leaf(self):
        self.assertNotEqual(Leaf(Primitive(int)), "not a leaf")
        self.assertNotEqual(Leaf(Primitive(int)), None)
        self.assertNotEqual(Leaf(Primitive(int)), Primitive(int))


class TestBranchEquivalence(unittest.TestCase):
    """Tests for Branch equivalence — null-invariant, name-invariant."""

    def test_identical_branches(self):
        b1 = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        b2 = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        self.assertEqual(b1, b2)

    def test_subset_equivalence_null_invariant(self):
        """Missing fields are OK: (a=int, b=str) == (a=int)."""
        b1 = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        b2 = Branch({"a": Leaf(Primitive(int))})
        self.assertEqual(b1, b2)

        # Reverse direction
        self.assertEqual(b2, b1)

    def test_subset_with_none_value(self):
        """(a=int, b=str) == (a=int, b=None) — null invariance."""
        b1 = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        b2 = Branch({"a": Leaf(Primitive(int)), "b": Leaf(NullType())})
        self.assertEqual(b1, b2)

    def test_name_invariance_different_fields(self):
        """Different field names break equivalence."""
        b1 = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        b2 = Branch({"a": Leaf(Primitive(int)), "c": Leaf(Primitive(str))})
        self.assertNotEqual(b1, b2)

    def test_disjoint_fields(self):
        """No subset relationship → not equivalent."""
        b1 = Branch({"a": Leaf(Primitive(int))})
        b2 = Branch({"b": Leaf(Primitive(str))})
        self.assertNotEqual(b1, b2)

    def test_nested_branch_equivalence(self):
        """Subset equivalence propagates through nested branches."""
        b1 = Branch({
            "a": Branch({
                "x": Leaf(Primitive(int)),
                "y": Leaf(Primitive(str)),
            }),
        })
        b2 = Branch({
            "a": Branch({
                "x": Leaf(Primitive(int)),
            }),
        })
        self.assertEqual(b1, b2)

    def test_nested_branch_inequivalence(self):
        """Different nested field names break equivalence."""
        b1 = Branch({
            "a": Branch({
                "x": Leaf(Primitive(int)),
            }),
        })
        b2 = Branch({
            "a": Branch({
                "z": Leaf(Primitive(int)),
            }),
        })
        self.assertNotEqual(b1, b2)

    def test_non_transitivity(self):
        """A==B, B==C, but A!=C — the defining property."""
        # A: (a=int, b=int)
        # B: (b=int)
        # C: (b=int, c=int)
        A = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(int))})
        B = Branch({"b": Leaf(Primitive(int))})
        C = Branch({"b": Leaf(Primitive(int)), "c": Leaf(Primitive(int))})

        self.assertEqual(A, B)  # A has superset of B's fields
        self.assertEqual(B, C)  # C has superset of B's fields
        self.assertNotEqual(A, C)  # A and C have disjoint extra fields

    def test_hash_consistency(self):
        """Equal branches must have equal hashes."""
        b1 = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        b2 = Branch({"a": Leaf(Primitive(int))})
        self.assertEqual(b1, b2)
        self.assertEqual(hash(b1), hash(b2))


class TestSchemaInference(unittest.TestCase):
    """Tests for infer_schema from Python objects."""

    def test_infer_none(self):
        result = infer_schema(None)
        self.assertIsInstance(result, Leaf)
        self.assertIsInstance(result.type, NullType)

    def test_infer_primitive(self):
        result = infer_schema(42)
        self.assertIsInstance(result, Leaf)
        self.assertEqual(result.type, Primitive(int))

        result = infer_schema("hello")
        self.assertIsInstance(result, Leaf)
        self.assertEqual(result.type, Primitive(str))

        result = infer_schema(3.14)
        self.assertIsInstance(result, Leaf)
        self.assertEqual(result.type, Primitive(float))

        result = infer_schema(True)
        self.assertIsInstance(result, Leaf)
        self.assertEqual(result.type, Primitive(bool))

    def test_infer_simple_dict(self):
        result = infer_schema({"a": 1, "b": "str", "c": None})
        self.assertIsInstance(result, Branch)
        self.assertIn("a", result.fields)
        self.assertIn("b", result.fields)
        self.assertIn("c", result.fields)
        self.assertEqual(result.fields["a"].type, Primitive(int))
        self.assertEqual(result.fields["b"].type, Primitive(str))
        self.assertIsInstance(result.fields["c"].type, NullType)

    def test_infer_nested_dict(self):
        result = infer_schema({"a": {"b": 1, "c": "text"}})
        self.assertIsInstance(result, Branch)
        self.assertIsInstance(result.fields["a"], Branch)
        self.assertEqual(result.fields["a"].fields["b"].type, Primitive(int))
        self.assertEqual(result.fields["a"].fields["c"].type, Primitive(str))

    def test_infer_empty_list(self):
        result = infer_schema([])
        self.assertIsInstance(result, Leaf)
        self.assertIsInstance(result.type, ListType)
        self.assertIsInstance(result.type.item_type, NullType)

    def test_infer_homogeneous_list(self):
        result = infer_schema([1, 2, 3])
        self.assertIsInstance(result, Leaf)
        self.assertIsInstance(result.type, ListType)
        self.assertEqual(result.type.item_type, Primitive(int))

    def test_infer_mixed_list(self):
        result = infer_schema([1, "two", 3])
        self.assertIsInstance(result, Leaf)
        self.assertIsInstance(result.type, ListType)
        self.assertIsInstance(result.type.item_type, UnionType)

    def test_infer_list_of_dicts(self):
        result = infer_schema([{"a": 1}, {"a": 2, "b": "x"}])
        self.assertIsInstance(result, Leaf)
        self.assertIsInstance(result.type, ListType)
        # item_type should be a Branch (reconciled from both dicts)
        self.assertIsInstance(result.type.item_type, Branch)


class TestReconciliation(unittest.TestCase):
    """Tests for schema reconciliation."""

    def test_reconcile_pair_simple(self):
        b1 = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        b2 = Branch({"a": Leaf(Primitive(int))})
        result = b1.reconcile_with(b2)

        self.assertIn("a", result.fields)
        self.assertIn("b", result.fields)
        # 'b' was missing in b2, so it should be Union[int, Null]
        b_type = result.fields["b"].type
        self.assertIsInstance(b_type, UnionType)
        self.assertIn(NullType(), b_type.types)

    def test_reconcile_pair_type_widening(self):
        b1 = Branch({"a": Leaf(Primitive(int))})
        b2 = Branch({"a": Leaf(Primitive(str))})
        result = b1.reconcile_with(b2)

        self.assertIn("a", result.fields)
        self.assertIsInstance(result.fields["a"].type, UnionType)
        self.assertIn(Primitive(int), result.fields["a"].type.types)
        self.assertIn(Primitive(str), result.fields["a"].type.types)

    def test_reconcile_pair_nested(self):
        b1 = Branch({
            "a": Branch({"x": Leaf(Primitive(int)), "y": Leaf(Primitive(str))}),
        })
        b2 = Branch({
            "a": Branch({"x": Leaf(Primitive(int))}),
        })
        result = b1.reconcile_with(b2)

        self.assertIn("a", result.fields)
        inner = result.fields["a"]
        self.assertIsInstance(inner, Branch)
        self.assertIn("y", inner.fields)
        self.assertIsInstance(inner.fields["y"].type, UnionType)

    def test_reconcile_non_equivalent_raises(self):
        b1 = Branch({"a": Leaf(Primitive(int))})
        b2 = Branch({"b": Leaf(Primitive(str))})
        with self.assertRaises(ValueError):
            b1.reconcile_with(b2)

    def test_reconcile_multi_branch(self):
        """Reconcile three branches to re-establish transitivity."""
        A = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(int))})
        B = Branch({"b": Leaf(Primitive(int))})
        C = Branch({"b": Leaf(Primitive(int)), "c": Leaf(Primitive(int))})

        result = reconcile([A, B, C])
        # Should have all three fields
        self.assertIn("a", result.fields)
        self.assertIn("b", result.fields)
        self.assertIn("c", result.fields)
        # 'a' and 'c' should be widened to Union[..., Null]
        self.assertIsInstance(result.fields["a"].type, UnionType)
        self.assertIsInstance(result.fields["c"].type, UnionType)

    def test_reconcile_empty(self):
        result = reconcile([])
        self.assertIsInstance(result, Branch)
        self.assertEqual(len(result.fields), 0)

    def test_reconcile_single(self):
        b = Branch({"a": Leaf(Primitive(int))})
        result = reconcile([b])
        self.assertEqual(result, b)


class TestSchemaClass(unittest.TestCase):
    """Tests for the high-level Schema interface."""

    def test_from_record(self):
        s = Schema.from_record({"a": 1, "b": "hello"})
        self.assertIsInstance(s.root, Branch)
        self.assertIn("a", s.root.fields)
        self.assertIn("b", s.root.fields)

    def test_from_records_single(self):
        s = Schema.from_records([{"a": 1}])
        self.assertIn("a", s.root.fields)

    def test_from_records_multiple(self):
        s = Schema.from_records([
            {"a": 1, "b": "x"},
            {"a": 2},
            {"b": "y", "c": 3.0},
        ])
        self.assertIn("a", s.root.fields)
        self.assertIn("b", s.root.fields)
        self.assertIn("c", s.root.fields)

    def test_from_records_empty(self):
        s = Schema.from_records([])
        self.assertIsInstance(s.root, Branch)
        self.assertEqual(len(s.root.fields), 0)

    def test_filter_matching(self):
        s = Schema.from_record({"a": 1, "b": "x"})
        records = [
            {"a": 1, "b": "x"},
            {"a": 2},
            {"b": "y"},
            {"a": 3, "b": "z", "c": 99},
        ]
        filtered = s.filter(records)
        # All records are equivalent under subset semantics:
        # {a,b} subset of {a,b}, {a} subset of {a,b}, {b} not subset, {a,b,c} superset
        # Wait: {b} is NOT a subset of {a,b} because {b} has field 'b' and {a,b} has 'b' too
        # Actually {b} IS a subset of {a,b} — keys_self={b} ⊆ keys_other={a,b} → True
        # So all 4 match under subset equivalence
        self.assertEqual(len(filtered), 4)

    def test_schema_equality(self):
        s1 = Schema.from_record({"a": 1, "b": "x"})
        s2 = Schema.from_record({"a": 1})
        self.assertEqual(s1, s2)

        s3 = Schema.from_record({"c": 1})
        self.assertNotEqual(s1, s3)


class TestVisualization(unittest.TestCase):
    """Tests for terminal and HTML visualization."""

    def test_leaf_tree_lines(self):
        leaf = Leaf(Primitive(int))
        lines = leaf._tree_lines()
        self.assertEqual(lines, ["int"])

    def test_branch_tree_lines_simple(self):
        b = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        lines = b._tree_lines()
        self.assertEqual(lines[0], "Root")
        self.assertIn("a : int", lines[1])
        self.assertIn("b : str", lines[2])

    def test_branch_tree_lines_nested(self):
        b = Branch({
            "a": Branch({
                "x": Leaf(Primitive(int)),
            }),
            "b": Leaf(Primitive(str)),
        })
        lines = b._tree_lines()
        self.assertEqual(lines[0], "Root")
        # Should have tree-drawing characters
        tree_text = "\n".join(lines)
        self.assertIn("├──", tree_text)
        self.assertIn("└──", tree_text)

    def test_branch_tree_lines_empty(self):
        b = Branch({})
        lines = b._tree_lines()
        self.assertEqual(lines, ["Root"])

    def test_repr_html_contains_expected_tags(self):
        b = Branch({"a": Leaf(Primitive(int))})
        html = b._repr_html_impl()
        self.assertIn("<details", html)
        self.assertIn("<summary>", html)
        self.assertIn("<b>Root</b>", html)
        self.assertIn("<b>a</b>", html)
        self.assertIn("int", html)

    def test_str_method(self):
        b = Branch({"a": Leaf(Primitive(int))})
        s = str(b)
        self.assertIn("Root", s)
        self.assertIn("a", s)
        self.assertIn("int", s)

    def test_schema_str(self):
        s = Schema.from_record({"a": 1})
        text = str(s)
        self.assertIn("Root", text)
        self.assertIn("a", text)

    def test_schema_repr_html(self):
        s = Schema.from_record({"a": 1})
        html = s._repr_html_()
        self.assertIn("<details", html)
        self.assertIn("<b>Root</b>", html)


class TestTypeStats(unittest.TestCase):
    """Tests for type ratio statistics."""

    def test_simple_stats(self):
        b = Branch({"a": Leaf(Primitive(int)), "b": Leaf(Primitive(str))})
        records = [
            {"a": 1, "b": "x"},
            {"a": 2, "b": "y"},
            {"a": 3, "b": None},
        ]
        stats = b.type_stats(records)
        self.assertIn("a", stats)
        self.assertIn("b", stats)
        # 'a' is always int
        self.assertEqual(stats["a"]["int"], 1.0)
        # 'b' is str 2/3, Null 1/3
        self.assertAlmostEqual(stats["b"]["str"], 2 / 3)
        self.assertAlmostEqual(stats["b"]["Null"], 1 / 3)

    def test_empty_stats(self):
        b = Branch({"a": Leaf(Primitive(int))})
        stats = b.type_stats([])
        self.assertEqual(stats, {})

    def test_nested_stats(self):
        b = Branch({
            "a": Branch({
                "x": Leaf(Primitive(int)),
            }),
        })
        records = [
            {"a": {"x": 1}},
            {"a": {"x": 2}},
        ]
        stats = b.type_stats(records)
        self.assertIn("a.x", stats)
        self.assertEqual(stats["a.x"]["int"], 1.0)


class TestDataTreeSchema(unittest.TestCase):
    """Tests for DataTree.schema integration."""

    def test_schema_property(self):
        dt = DataTree.from_records([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ])
        s = dt.schema
        self.assertIsInstance(s, Schema)
        self.assertIn("name", s.root.fields)
        self.assertIn("age", s.root.fields)

    def test_schema_with_mixed_types(self):
        dt = DataTree.from_records([
            {"a": 1},
            {"a": "hello"},
        ])
        s = dt.schema
        self.assertIsInstance(s.root.fields["a"].type, UnionType)

    def test_schema_after_filter(self):
        dt = DataTree.from_records([
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
            {"name": "Charlie", "age": 35},
        ])
        filtered = dt.filter(lambda r, m: r.data["age"] > 28)
        s = filtered.schema
        self.assertIn("name", s.root.fields)
        self.assertIn("age", s.root.fields)

    def test_schema_empty_tree(self):
        dt = DataTree.from_records([])
        s = dt.schema
        self.assertEqual(len(s.root.fields), 0)


class TestDataTreeInspect(unittest.TestCase):
    """Tests for DataTree.inspect(indexer)."""

    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30, "city": "New York",
             "education": {"degree": "Bachelor's", "level": 1}},
            {"name": "Bob", "age": 25, "city": "Los Angeles",
             "education": {"degree": "Master's", "level": 2}},
            {"name": "Charlie", "age": 35, "city": "Chicago",
             "education": {"degree": "PhD", "level": 3}},
        ]
        self.dt = DataTree.from_records(self.records)

    def test_inspect_simple_string(self):
        """String indexer returns schema named after the field."""
        s = self.dt.inspect("age")
        self.assertIsInstance(s, Schema)
        self.assertEqual(s.name, "age")
        # r.get("age") returns {"age": 30} → Branch({"age": Leaf(int)})
        self.assertIn("age", s.root.fields)

    def test_inspect_dotted_path(self):
        """Dotted string indexer preserves nested structure."""
        s = self.dt.inspect("education.degree")
        self.assertIsInstance(s, Schema)
        self.assertEqual(s.name, "education.degree")
        # r.get("education.degree") returns {"education": {"degree": "str"}}
        # → Branch({"education": Branch({"degree": Leaf(str)})})
        self.assertIn("education", s.root.fields)
        self.assertIsInstance(s.root.fields["education"], Branch)
        self.assertIn("degree", s.root.fields["education"].fields)

    def test_inspect_nested_dict(self):
        """Indexer pointing to a nested dict returns full subtree schema."""
        s = self.dt.inspect("education")
        self.assertIsInstance(s, Schema)
        self.assertEqual(s.name, "education")
        # r.get("education") returns {"education": {"degree": ..., "level": ...}}
        # → Branch({"education": Branch({"degree": ..., "level": ...})})
        self.assertIn("education", s.root.fields)
        inner = s.root.fields["education"]
        self.assertIsInstance(inner, Branch)
        self.assertIn("degree", inner.fields)
        self.assertIn("level", inner.fields)

    def test_inspect_list_indexer(self):
        """List indexer returns combined schema of multiple fields."""
        s = self.dt.inspect(["name", "age"])
        self.assertIsInstance(s, Schema)
        # r.get(["name", "age"]) merges: {"name": ..., "age": ...}
        self.assertIn("name", s.root.fields)
        self.assertIn("age", s.root.fields)

    def test_inspect_missing_field(self):
        """Missing field values become Null in the schema."""
        dt = DataTree.from_records([
            {"a": 1},
            {"b": 2},
        ])
        s = dt.inspect("a")
        # One record has 'a', the other doesn't — 'a' should be Union[int, Null]
        self.assertIn("a", s.root.fields)
        a_type = s.root.fields["a"].type
        self.assertIsInstance(a_type, UnionType)
        self.assertIn(NullType(), a_type.types)

    def test_inspect_empty_tree(self):
        """Empty tree returns an empty Branch."""
        dt = DataTree.from_records([])
        s = dt.inspect("anything")
        self.assertIsInstance(s.root, Branch)
        self.assertEqual(len(s.root.fields), 0)

    def test_inspect_name_display(self):
        """The schema name appears in string representation."""
        s = self.dt.inspect("age")
        text = str(s)
        self.assertIn("age", text)

    def test_inspect_with_indexer_resolution(self):
        """Tuple and dict indexers also work.  Tuple = parallel projection."""
        dt = DataTree.from_records([
            {"x": {"y": 10}},
            {"x": {"y": 20}},
        ])
        # Tuple indexer: ("x",) means project field 'x'
        s = dt.inspect(("x",))
        self.assertIn("x", s.root.fields)
        # The value at 'x' is a dict {"y": 10}, so x is a Branch
        self.assertIsInstance(s.root.fields["x"], Branch)

    def test_show_list(self):
        """Verify show_list doesn't crash."""
        s1 = Schema.from_record({"a": 1})
        s2 = Schema.from_record({"b": "x"})
        Schema.show_list([s1, s2])

    def test_inspect_mismatch_returns_list(self):
        """If reconciliation fails, return a list of unique schemas."""
        dt = DataTree.from_records([
            {"a": {"b": 1}},
            {"a": 2},
        ])
        result = dt.inspect("a")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], Schema)
        self.assertIsInstance(result[1], Schema)


if __name__ == "__main__":
    unittest.main()