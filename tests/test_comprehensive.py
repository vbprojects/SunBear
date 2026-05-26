import unittest
import warnings
import itertools
from typing import Callable
from sunbear.Schema import (
    Path,
    PrimitiveType,
    NullType,
    UnionType,
    ListType,
    FunctionType,
    ThunkFunctionType,
    Leaf,
    Branch,
    infer_schema
)
from sunbear.DataTree import DataTree
from sunbear.DataBranch import DataBranch
from sunbear.utils import isna


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────

@DataTree.register_method
@DataBranch.register_method
def head(db, n=5):
    """Return the first N records."""
    return DataBranch(db, operation=lambda r: list(itertools.islice(r, n)))


@DataTree.register_method
@DataBranch.register_method
def filter(db, func):
    """Filter records using a predicate on the projected column."""
    return db.shallow(func)


# ──────────────────────────────────────────────────────────────────────
# 1. Schema Operations
# ──────────────────────────────────────────────────────────────────────

class TestSchemaDiff(unittest.TestCase):
    def test_diff_identical(self):
        s1 = infer_schema({"a": 1, "b": "x"})
        s2 = infer_schema({"a": 1, "b": "x"})
        diff = s1.diff(s2)
        self.assertEqual(diff.fields, {})

    def test_diff_missing_field(self):
        s1 = infer_schema({"a": 1, "b": "x"})
        s2 = infer_schema({"a": 1})
        diff = s1.diff(s2)
        self.assertIn("b", diff.fields)

    def test_diff_type_change(self):
        s1 = infer_schema({"a": 1})
        s2 = infer_schema({"a": "x"})
        diff = s1.diff(s2)
        self.assertIn("a", diff.fields)
        self.assertIsInstance(diff.fields["a"].type, UnionType)

    def test_diff_nested(self):
        s1 = infer_schema({"a": {"b": 1, "c": "x"}})
        s2 = infer_schema({"a": {"b": 1}})
        diff = s1.diff(s2)
        self.assertIn("a", diff.fields)
        self.assertIn("c", diff.fields["a"].fields)


# ──────────────────────────────────────────────────────────────────────
# 2. DataBranch Core Operations
# ──────────────────────────────────────────────────────────────────────

class TestDataBranchShallow(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30, "city": "New York"},
            {"name": "Bob", "age": 25, "city": "Los Angeles"},
            {"name": "Charlie", "age": 35, "city": "Chicago"},
        ]
        self.dt = DataTree(self.records)

    def test_shallow_filter(self):
        # shallow filter with projection: collect() applies projection AFTER shallow,
        # so we get projected values (ages) for records that pass the predicate
        result = self.dt[:, "age"].shallow(lambda x: x > 28).collect()
        self.assertEqual(result, [30, 35])

    def test_shallow_mutate(self):
        result = self.dt[:, "age"].shallow(lambda x: x * 2).collect()
        self.assertEqual(result, [60, 50, 70])

    def test_shallow_filter_no_projection(self):
        result = self.dt.shallow(lambda r: r["age"] > 28).collect()
        self.assertEqual(len(result), 2)
        names = [r["name"] for r in result]
        self.assertIn("Alice", names)
        self.assertIn("Charlie", names)


class TestDataBranchDeep(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "tags": [1, 2, 3]},
            {"name": "Bob", "tags": [4, 5]},
        ]
        self.dt = DataTree(self.records)

    def test_deep_transform(self):
        result = self.dt.deep(lambda x: x * 10 if isinstance(x, int) else x).collect()
        self.assertEqual(result[0]["tags"], [10, 20, 30])

    def test_deep_filter(self):
        # deep() replaces values that fail the predicate with None, but doesn't remove them
        result = self.dt.deep(lambda x: x if isinstance(x, int) and x > 2 else None).collect()
        self.assertEqual(result[0]["tags"], [None, None, 3])


class TestDataBranchIsna(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30},
            {"name": "Bob"},
            {"name": "Charlie", "age": None},
        ]
        self.dt = DataTree(self.records)

    def test_isna_filter(self):
        result = self.dt[:, "age"].isna().collect()
        self.assertEqual(len(result), 2)

    def test_not_isna_filter(self):
        result = self.dt[:, "age"].not_(isna).collect()
        # Returns projected values (ages) for records where age is not None
        self.assertEqual(result, [30])


class TestDataBranchAssign(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        self.dt = DataTree(self.records)

    def test_assign_scalar(self):
        result = self.dt[:, "age"].assign(99).collect()
        self.assertIsInstance(result, DataTree)
        records = list(result.records)
        self.assertEqual(records[0]["age"], 99)
        self.assertEqual(records[1]["age"], 99)

    def test_assign_nested(self):
        self.records_nested = [
            {"name": "Alice", "addr": {"city": "NYC"}},
        ]
        dt = DataTree(self.records_nested)
        result = dt[:, "addr.city"].assign("LA").collect()
        records = list(result.records)
        self.assertEqual(records[0]["addr"]["city"], "LA")


# ──────────────────────────────────────────────────────────────────────
# 3. Indexing & Projection
# ──────────────────────────────────────────────────────────────────────

class TestIndexing(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30, "city": "New York"},
            {"name": "Bob", "age": 25, "city": "Los Angeles"},
            {"name": "Charlie", "age": 35, "city": "Chicago"},
        ]
        self.dt = DataTree(self.records)

    def test_row_slice(self):
        result = self.dt[1:, "name"].collect()
        self.assertEqual(result, ["Bob", "Charlie"])

    def test_row_int(self):
        result = self.dt[0, "name"].collect()
        self.assertEqual(result, ["Alice"])

    def test_row_list(self):
        result = self.dt[[0, 2], "name"].collect()
        self.assertEqual(result, ["Alice", "Charlie"])

    def test_schema_pruning(self):
        result = self.dt[{"name": None, "age": None}, :].collect()
        for r in result:
            self.assertIn("name", r)
            self.assertIn("age", r)
            self.assertNotIn("city", r)

    def test_breadth_projection(self):
        result = self.dt[:, ["name", "city"]].collect()
        self.assertEqual(result, [
            ["Alice", "New York"],
            ["Bob", "Los Angeles"],
            ["Charlie", "Chicago"],
        ])

    def test_depth_traversal(self):
        records = [
            {"a": {"b": {"c": 1}}},
            {"a": {"b": {"c": 2}}},
        ]
        dt = DataTree(records)
        result = dt[:, "a.b.c"].collect()
        self.assertEqual(result, [1, 2])


# ──────────────────────────────────────────────────────────────────────
# 4. List-of-Records Traversal (Sub-DataTree)
# ──────────────────────────────────────────────────────────────────────

class TestListTraversal(unittest.TestCase):
    def setUp(self):
        self.records = [
            {
                "name": "Alice",
                "companies": [
                    {"name": "Google", "position": "SWE"},
                    {"name": "Facebook", "position": "DS"},
                ],
            },
            {
                "name": "Bob",
                "companies": [
                    {"name": "Amazon", "position": "DE"},
                ],
            },
            {"name": "Charlie"},  # no companies
        ]
        self.dt = DataTree(self.records)

    def test_list_of_records_projection(self):
        result = self.dt[:, "companies.name"].collect()
        self.assertEqual(result, [["Google", "Facebook"], ["Amazon"], None])

    def test_list_of_records_nested(self):
        result = self.dt[:, "companies.position"].collect()
        self.assertEqual(result, [["SWE", "DS"], ["DE"], None])

    def test_resolve_path_static(self):
        val = {"companies": [{"name": "A"}, {"name": "B"}]}
        result = DataBranch._resolve_path(val, ["companies", "name"])
        self.assertEqual(result, ["A", "B"])

    def test_resolve_path_missing(self):
        val = {"other": "x"}
        result = DataBranch._resolve_path(val, ["companies", "name"])
        self.assertIsNone(result)


# ──────────────────────────────────────────────────────────────────────
# 5. Aggregation & Partitioning
# ──────────────────────────────────────────────────────────────────────

class TestGroupBy(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30, "city": "New York", "occupation": "Engineer"},
            {"name": "Bob", "age": 25, "city": "Los Angeles", "occupation": "Engineer"},
            {"name": "Charlie", "age": 35, "city": "Chicago", "occupation": "Manager"},
            {"name": "David", "age": 40, "city": "New York", "occupation": "Manager"},
        ]
        self.dt = DataTree(self.records)

    def test_group_by_single(self):
        result = self.dt[:, "occupation"].group_by().collect()
        records = list(result.records)
        self.assertEqual(len(records), 2)
        # Check that both groups exist
        occupations = {r["occupation"] for r in records}
        self.assertEqual(occupations, {"Engineer", "Manager"})

    def test_group_by_member_count(self):
        result = self.dt[:, "occupation"].group_by().collect()
        records = list(result.records)
        for r in records:
            self.assertIn("members", r)
            self.assertIsInstance(r["members"], list)

    def test_group_by_city(self):
        result = self.dt[:, "city"].group_by().collect()
        records = list(result.records)
        cities = {r["city"] for r in records}
        self.assertEqual(cities, {"New York", "Los Angeles", "Chicago"})

    def test_chained_group_by(self):
        result = (
            self.dt[:, "city"]
            .group_by()
            [:, "members.occupation"]
            .group_by()
            .collect()
        )
        records = list(result.records)
        # Should have 3 outer groups (cities)
        self.assertEqual(len(records), 3)
        # Each outer group should have nested members grouped by occupation
        for outer in records:
            self.assertIn("city", outer)
            self.assertIn("members", outer)
            for inner in outer["members"]:
                self.assertIn("occupation", inner)
                self.assertIn("members", inner)


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"Engineer": {"name": "Alice"}},
            {"Engineer": {"name": "Bob"}},
            {"name": "Charlie"},  # no Engineer key
        ]
        self.dt = DataTree(self.records)

    def test_aggregate_groups_matching(self):
        result = self.dt[:, "Engineer"].aggregate().collect()
        records = list(result.records)
        # Should have 2 records: one aggregated, one unaggregated
        self.assertEqual(len(records), 2)
        agg = records[0]
        self.assertIn("Engineer", agg)
        self.assertIsInstance(agg["Engineer"], list)
        self.assertEqual(len(agg["Engineer"]), 2)

    def test_aggregate_skips_none(self):
        result = self.dt[:, "Engineer"].aggregate().collect()
        records = list(result.records)
        unagg = records[1]
        self.assertNotIn("Engineer", unagg)
        self.assertEqual(unagg["name"], "Charlie")


class TestAddPath(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "occupation": "Engineer"},
            {"name": "Bob", "occupation": "Engineer"},
            {"name": "Charlie", "occupation": "Manager"},
        ]
        self.dt = DataTree(self.records)

    def test_add_path_wrap_root(self):
        db = self.dt[:, "occupation"].filter(lambda x: x == "Engineer")
        result = db.add_path("..", db[:, "occupation"]).collect()
        records = list(result.records)
        self.assertEqual(len(records), 2)
        for r in records:
            self.assertIn("Engineer", r)

    def test_add_path_nested(self):
        result = self.dt.add_path("meta.role", self.dt[:, "occupation"]).collect()
        records = list(result.records)
        self.assertEqual(records[0]["meta"]["role"], "Engineer")
        self.assertEqual(records[2]["meta"]["role"], "Manager")


# ──────────────────────────────────────────────────────────────────────
# 6. .path() Method
# ──────────────────────────────────────────────────────────────────────

class TestPathMethod(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30, "city": "New York"},
            {"name": "Bob", "age": 25, "city": "Los Angeles"},
        ]
        self.dt = DataTree(self.records)

    def test_path_single_string(self):
        result = self.dt.path("name").collect()
        records = list(result.records)
        self.assertEqual(records[0], {"name": "Alice"})

    def test_path_single_tuple(self):
        result = self.dt.path(("name",)).collect()
        records = list(result.records)
        self.assertEqual(records[0], {"name": "Alice"})

    def test_path_multiple_strings(self):
        result = self.dt.path(["name", "age"]).collect()
        records = list(result.records)
        self.assertEqual(records[0], {"name": "Alice", "age": 30})

    def test_path_multiple_tuples(self):
        result = self.dt.path([("name",), ("city",)]).collect()
        records = list(result.records)
        self.assertEqual(records[0], {"name": "Alice", "city": "New York"})

    def test_path_returns_datatree(self):
        result = self.dt.path("name").collect()
        self.assertIsInstance(result, DataTree)

    def test_path_nested(self):
        records = [
            {"a": {"b": {"c": 1}}},
            {"a": {"b": {"c": 2}}},
        ]
        dt = DataTree(records)
        result = dt.path("a.b.c").collect()
        recs = list(result.records)
        self.assertEqual(recs[0], {"c": 1})

    def test_path_list_of_records(self):
        records = [
            {"items": [{"val": 1}, {"val": 2}]},
            {"items": [{"val": 3}]},
        ]
        dt = DataTree(records)
        result = dt.path("items.val").collect()
        recs = list(result.records)
        # _resolve_path maps across the list, returning [1, 2] (not [[1, 2]])
        self.assertEqual(recs[0], {"val": [1, 2]})


# ──────────────────────────────────────────────────────────────────────
# 7. Extension System
# ──────────────────────────────────────────────────────────────────────

class TestExtensionSystem(unittest.TestCase):
    def test_register_method_on_datatree(self):
        self.assertTrue(hasattr(DataTree, "head"))
        self.assertTrue(hasattr(DataTree, "path"))
        self.assertTrue(hasattr(DataTree, "group_by"))
        self.assertTrue(hasattr(DataTree, "aggregate"))
        self.assertTrue(hasattr(DataTree, "add_path"))

    def test_register_method_on_databranch(self):
        self.assertTrue(hasattr(DataBranch, "head"))
        self.assertTrue(hasattr(DataBranch, "path"))
        self.assertTrue(hasattr(DataBranch, "group_by"))
        self.assertTrue(hasattr(DataBranch, "aggregate"))
        self.assertTrue(hasattr(DataBranch, "add_path"))

    def test_extension_composable(self):
        records = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
            {"name": "Charlie", "age": 35},
        ]
        dt = DataTree(records)
        # Chain head -> filter -> path
        result = dt.head(n=2).path("name").collect()
        self.assertIsInstance(result, DataTree)
        recs = list(result.records)
        self.assertEqual(len(recs), 2)


# ──────────────────────────────────────────────────────────────────────
# 8. Edge Cases
# ──────────────────────────────────────────────────────────────────────

class TestEdgeCases(unittest.TestCase):
    def test_empty_tree(self):
        dt = DataTree([])
        self.assertEqual(len(dt), 0)
        self.assertEqual(dt.schemas(), {})

    def test_single_record(self):
        dt = DataTree([{"a": 1}])
        self.assertEqual(len(dt), 1)
        result = dt[:, "a"].collect()
        self.assertEqual(result, [1])

    def test_deferred_evaluation(self):
        dt = DataTree([{"a": 1}, {"b": 2}], defer_evaluation=True)
        self.assertEqual(dt._schemas, {})
        # Trigger evaluation
        dt.build_schemas()
        self.assertGreater(len(dt._schemas), 0)

    def test_deeply_nested(self):
        records = [{"a": {"b": {"c": {"d": {"e": 42}}}}}]
        dt = DataTree(records)
        result = dt[:, "a.b.c.d.e"].collect()
        self.assertEqual(result, [42])

    def test_mixed_types_in_field(self):
        records = [
            {"val": 1},
            {"val": "x"},
            {"val": None},
        ]
        dt = DataTree(records)
        result = dt[:, "val"].collect()
        self.assertEqual(result, [1, "x", None])

    def test_chained_operations_no_materialization(self):
        records = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        dt = DataTree(records)
        # Build a chain without collecting
        branch = dt[:, "age"].shallow(lambda x: x > 25)
        self.assertIsInstance(branch, DataBranch)
        result = branch.collect()
        self.assertEqual(len(result), 1)


# ──────────────────────────────────────────────────────────────────────
# 9. Collect Return Types
# ──────────────────────────────────────────────────────────────────────

class TestCollectReturnTypes(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        self.dt = DataTree(self.records)

    def test_collect_projection_returns_list(self):
        result = self.dt[:, "age"].collect()
        self.assertIsInstance(result, list)
        self.assertEqual(result, [30, 25])

    def test_collect_no_projection_returns_list(self):
        result = self.dt.head().collect()
        self.assertIsInstance(result, list)

    def test_collect_group_by_returns_datatree(self):
        result = self.dt[:, "name"].group_by().collect()
        self.assertIsInstance(result, DataTree)

    def test_collect_path_returns_datatree(self):
        result = self.dt.path("name").collect()
        self.assertIsInstance(result, DataTree)

    def test_collect_assign_returns_datatree(self):
        result = self.dt[:, "age"].assign(99).collect()
        self.assertIsInstance(result, DataTree)


if __name__ == "__main__":
    unittest.main()
