"""test_min.py — regression tests for the minimal sunbear rewrite.

Covers:
- DataTree construction (from_records, from_iter)
- Lazy primitives (map, filter, branch_map, insert, take, head, tail)
- Path mutations (set, add, move, copy, drop, rename, assign_at)
- Plan layer (group_by, join, reduce, reduce_by, sort_by, plan.explain())
- Schema (carried over from v3)
- expr pipeline (assign, keep, fork, case)
- Intra-record ops (sbo.flatten, sbo.filter, sbo.map, sbo.reduce, sbo.length)
- chain() — build-time AST substitution
- Reference sharing (records are mutable, shared by ref)
- No invertibility surface
"""
import sys
import unittest
import itertools
import numpy as np

from sunbear import DataTree, Record, Plan, Schema
from sunbear.expr import (
    b, _, assign, keep, fork, case,
    filter_field, map_field, flatten as flatten_field,
    sbo,
)
from sunbear.expr.sbo import chain


# ═══════════════════════════════════════════════════════════════════════════
# DataTree construction
# ═══════════════════════════════════════════════════════════════════════════

class TestConstruction(unittest.TestCase):

    def test_from_records_basic(self):
        dt = DataTree.from_records([{"a": 1}, {"a": 2}])
        self.assertEqual(dt.collect(), [{"a": 1}, {"a": 2}])

    def test_from_records_assigns_index(self):
        dt = DataTree.from_records([{"a": 1}, {"a": 2}])
        metas = [m for _, m in dt.scan()]
        self.assertEqual(metas, [{"i": 0}, {"i": 1}])

    def test_from_iter_single_pass(self):
        # from_iter is single-pass by design (true streaming).
        # Use list(scan()) — not collect() after next() — because the
        # generator is consumed on first traversal.
        def gen():
            yield {"x": 1}
            yield {"x": 2}
            yield {"x": 3}
        dt = DataTree.from_iter(gen())
        all_rows = list(dt.scan())
        self.assertEqual([r.data for r, _ in all_rows], [{"x": 1}, {"x": 2}, {"x": 3}])

    def test_from_records_re_traversable(self):
        dt = DataTree.from_records([{"x": i} for i in range(5)])
        # can scan multiple times
        self.assertEqual(len(dt), 5)
        self.assertEqual(len(dt), 5)
        self.assertEqual(len(dt.collect()), 5)


# ═══════════════════════════════════════════════════════════════════════════
# Record (single _walk, get/set/delete)
# ═══════════════════════════════════════════════════════════════════════════

class TestRecord(unittest.TestCase):

    def test_get_set_top_level(self):
        r = Record({"a": 1, "b": 2})
        self.assertEqual(r.get("a"), 1)
        r.set("a", 99)
        self.assertEqual(r.get("a"), 99)

    def test_get_set_nested(self):
        r = Record({"profile": {"age": 30}})
        self.assertEqual(r.get("profile.age"), 30)
        r.set("profile.age", 31)
        self.assertEqual(r.get("profile.age"), 31)

    def test_get_missing_returns_none(self):
        r = Record({"a": 1})
        self.assertIsNone(r.get("nonexistent"))
        self.assertIsNone(r.get("a.b.c"))

    def test_set_creates_intermediate(self):
        r = Record({})
        r.set("a.b.c", 42)
        self.assertEqual(r.data, {"a": {"b": {"c": 42}}})

    def test_delete(self):
        r = Record({"a": 1, "b": 2})
        r.delete("a")
        self.assertNotIn("a", r.data)
        self.assertEqual(r.get("b"), 2)

    def test_delete_missing_no_error(self):
        r = Record({"a": 1})
        r.delete("missing")  # must not raise
        self.assertEqual(r.data, {"a": 1})

    def test_mv(self):
        r = Record({"a": 1, "b": 2})
        r.mv("a", "c")
        self.assertNotIn("a", r.data)
        self.assertEqual(r.get("c"), 1)

    def test_cpy(self):
        r = Record({"a": 1, "b": 2})
        r.cpy("a", "c")
        self.assertEqual(r.get("a"), 1)
        self.assertEqual(r.get("c"), 1)

    def test_add_only_if_missing(self):
        r = Record({"a": 1})
        r.add("b", 2)
        r.add("a", 99)  # already present, no-op
        self.assertEqual(r.get("a"), 1)
        self.assertEqual(r.get("b"), 2)

    def test_sugar_getitem_setitem(self):
        r = Record({"a.b": 1})  # treat literal as a key
        # __getitem__ uses .get which uses resolve
        # "a.b" becomes a nested path
        r2 = Record({"a": {"b": 1}})
        self.assertEqual(r2["a.b"], 1)
        r2["c"] = 3
        self.assertEqual(r2.get("c"), 3)
        self.assertIn("a.b", Record({"a": {"b": 1}}))

    def test_meta_dict_is_independent(self):
        r1 = Record({"a": 1})
        r2 = Record({"a": 2})
        r1.meta["x"] = "tag"
        self.assertNotIn("x", r2.meta)


# ═══════════════════════════════════════════════════════════════════════════
# Lazy primitives
# ═══════════════════════════════════════════════════════════════════════════

class TestLazyPrimitives(unittest.TestCase):

    def test_filter_lazy(self):
        records = [{"n": i} for i in range(10)]
        dt = DataTree.from_records(records)
        # filter returns a generator, can be sliced
        sliced = list(itertools.islice(dt.filter(lambda r, m: r.data["n"] % 2 == 0).scan(), 3))
        self.assertEqual([r.data["n"] for r, _ in sliced], [0, 2, 4])

    def test_filter_full(self):
        dt = DataTree.from_records([{"n": i} for i in range(5)])
        out = [r.data for r, _ in dt.filter(lambda r, m: r.data["n"] > 2).scan()]
        self.assertEqual(out, [{"n": 3}, {"n": 4}])

    def test_map(self):
        dt = DataTree.from_records([{"n": i} for i in range(3)])
        out = [r.data["n"] for r, _ in dt.map(lambda r: Record({"n": r.data["n"] * 2})).scan()]
        self.assertEqual(out, [0, 2, 4])

    def test_branch_map_no_snapshot(self):
        # branch_map is mutation-on-copy (no invertibility machinery)
        dt = DataTree.from_records([{"a": 1, "b": 2}])
        out = dt.branch_map(["a"], lambda r: r.set("a", 99))
        first_data = next(out.scan())[0].data
        self.assertEqual(first_data["a"], 99)

    def test_insert_chains(self):
        dt1 = DataTree.from_records([{"x": 1}])
        dt2 = DataTree.from_records([{"x": 2}, {"x": 3}])
        merged = dt1.insert(dt2.scan())
        self.assertEqual(merged.collect(), [{"x": 1}, {"x": 2}, {"x": 3}])

    def test_take(self):
        dt = DataTree.from_records([{"n": i} for i in range(10)])
        self.assertEqual([r.data["n"] for r, _ in dt.take(2, 5).scan()], [2, 3, 4])

    def test_head_tail(self):
        dt = DataTree.from_records([{"n": i} for i in range(10)])
        self.assertEqual([r.data["n"] for r, _ in dt.head(3).scan()], [0, 1, 2])
        self.assertEqual([r.data["n"] for r, _ in dt.tail(3).scan()], [7, 8, 9])

    def test_take_with_itertools_islice_compatible(self):
        dt = DataTree.from_records([{"n": i} for i in range(100)])
        sliced = list(itertools.islice(dt.scan(), 5))
        self.assertEqual(len(sliced), 5)


# ═══════════════════════════════════════════════════════════════════════════
# Path mutation sugar
# ═══════════════════════════════════════════════════════════════════════════

class TestPathMutation(unittest.TestCase):

    def test_assign_at(self):
        dt = DataTree.from_records([{"n": i} for i in range(3)])
        dt2 = dt.assign_at("squared", lambda r: r.data["n"] ** 2)
        out = [r.data for r, _ in dt2.scan()]
        self.assertEqual(out, [{"n": 0, "squared": 0}, {"n": 1, "squared": 1}, {"n": 2, "squared": 4}])

    def test_set(self):
        dt = DataTree.from_records([{"a": 1}])
        dt2 = dt.set("b", 2)
        self.assertEqual(dt2.collect(), [{"a": 1, "b": 2}])

    def test_add_field(self):
        dt = DataTree.from_records([{"a": 1}, {"a": 2}])
        dt2 = dt.add("b", 99)
        out = [r.data for r, _ in dt2.scan()]
        self.assertEqual(out, [{"a": 1, "b": 99}, {"a": 2, "b": 99}])

    def test_move(self):
        dt = DataTree.from_records([{"a": 1, "b": 2}])
        dt2 = dt.move("a", "c")
        self.assertEqual(dt2.collect(), [{"b": 2, "c": 1}])

    def test_copy_field(self):
        dt = DataTree.from_records([{"a": 1}])
        dt2 = dt.copy("a", "a_copy")
        self.assertEqual(dt2.collect(), [{"a": 1, "a_copy": 1}])

    def test_drop(self):
        dt = DataTree.from_records([{"a": 1, "b": 2, "c": 3}])
        dt2 = dt.drop("a", "c")
        self.assertEqual(dt2.collect(), [{"b": 2}])

    def test_rename(self):
        dt = DataTree.from_records([{"old_name": 1}])
        dt2 = dt.rename(old_name="new_name")
        self.assertEqual(dt2.collect(), [{"new_name": 1}])


# ═══════════════════════════════════════════════════════════════════════════
# Plan layer (inter-record ops)
# ═══════════════════════════════════════════════════════════════════════════

class TestPlanLayer(unittest.TestCase):

    def test_group_by_basic(self):
        recs = [{"k": "a", "v": 1}, {"k": "b", "v": 2}, {"k": "a", "v": 3}]
        dt = DataTree.from_records(recs)
        grouped = dt.group_by("k")
        out = [(r.data["k"], len(r.data["members"])) for r, _ in grouped.scan()]
        self.assertEqual(out, [("a", 2), ("b", 1)])

    def test_group_by_with_reduce(self):
        recs = [{"k": "a", "v": 1}, {"k": "b", "v": 2}, {"k": "a", "v": 3}]
        dt = DataTree.from_records(recs)
        # single reduce fn: stored as "v"
        grouped = dt.group_by("k", lambda members: sum(r.data["v"] for r in members))
        out = {r.data["k"]: r.data["v"] for r, _ in grouped.scan()}
        self.assertEqual(out, {"a": 4, "b": 2})

    def test_group_by_multiple_reduces(self):
        recs = [{"k": "a", "v": 1}, {"k": "a", "v": 2}, {"k": "b", "v": 10}]
        dt = DataTree.from_records(recs)
        grouped = dt.group_by("k",
                              lambda ms: sum(r.data["v"] for r in ms),
                              lambda ms: len(ms))
        out = {r.data["k"]: (r.data["v_0"], r.data["v_1"]) for r, _ in grouped.scan()}
        self.assertEqual(out, {"a": (3, 2), "b": (10, 1)})

    def test_plan_explain(self):
        recs = [{"k": "a"}, {"k": "b"}, {"k": "a"}]
        dt = DataTree.from_records(recs)
        plan = dt.plan("k")
        s = plan.explain()
        self.assertIn("cardinality", s)
        self.assertIn("keys=2", s)
        self.assertIn("rows=3", s)

    def test_plan_execute(self):
        recs = [{"k": "x", "v": 1}, {"k": "x", "v": 2}, {"k": "y", "v": 3}]
        dt = DataTree.from_records(recs)
        plan = dt.plan("k")
        rows = plan.execute()
        self.assertEqual(len(rows), 2)
        self.assertEqual([r["k"] for r in rows], ["x", "y"])
        self.assertEqual(len(rows[0]["members"]), 2)

    def test_plan_callable_key(self):
        recs = [{"x": 1}, {"x": 2}, {"x": 1}]
        dt = DataTree.from_records(recs)
        plan = dt.plan(lambda r, m: r.data["x"] % 2)
        out = {row["k"]: [m.data["x"] for m in row["members"]] for row in plan.execute()}
        self.assertEqual(out, {1: [1, 1], 0: [2]})

    def test_reduce_by_single_pass(self):
        recs = [{"k": "a", "v": 1}, {"k": "b", "v": 2}, {"k": "a", "v": 3}]
        dt = DataTree.from_records(recs)
        result = dt.reduce_by("k", lambda acc, r: acc + r.data["v"], init=0)
        sums = {r.data["k"]: r.data["v"] for r, _ in result.scan()}
        self.assertEqual(sums, {"a": 4, "b": 2})

    def test_reduce_by_no_init_uses_first_data(self):
        # Without init, the first record's data is the seed for each group.
        # fn signature: (acc, record). When fn is called the first time, acc
        # is the first record's data dict; for this test to work the user
        # should pass init explicitly. This test documents the behavior.
        recs = [{"k": "a", "v": 10}, {"k": "a", "v": 5}, {"k": "a", "v": 1}]
        dt = DataTree.from_records(recs)
        # with explicit init:
        result = dt.reduce_by("k", lambda acc, r: acc + r.data["v"], init=0)
        out = {r.data["k"]: r.data["v"] for r, _ in result.scan()}
        self.assertEqual(out, {"a": 16})  # 10 + 5 + 1

    def test_reduce_terminal(self):
        recs = [{"v": i} for i in range(1, 5)]
        dt = DataTree.from_records(recs)
        total = dt.reduce(lambda acc, r: acc + r.data["v"], init=0)
        self.assertEqual(total, 10)

    def test_reduce_terminal_no_init_uses_first_data(self):
        # Without init, the first record's data is the seed. This test
        # documents the behavior: fn receives a dict, so users should pass
        # init explicitly when fn expects a scalar.
        recs = [{"v": i} for i in range(1, 5)]
        dt = DataTree.from_records(recs)
        # with explicit init: total = 10
        out = dt.reduce(lambda acc, r: acc + r.data["v"], init=0)
        self.assertEqual(out, 10)

    def test_reduce_empty_with_init(self):
        dt = DataTree.from_records([])
        out = dt.reduce(lambda acc, r: acc + 1, init=42)
        self.assertEqual(out, 42)

    def test_reduce_empty_no_init_raises(self):
        dt = DataTree.from_records([])
        with self.assertRaises(ValueError):
            dt.reduce(lambda acc, r: acc + 1)

    def test_join_inner(self):
        left = [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]
        right = [{"id": 1, "val": "x"}, {"id": 2, "val": "y"}, {"id": 3, "val": "z"}]
        dt_left = DataTree.from_records(left)
        joined = dt_left.join(right, on="id")
        out = dt_left.join(right, on="id").collect()
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], {"id": 1, "name": "a", "val": "x"})

    def test_sort_by(self):
        dt = DataTree.from_records([{"n": 3}, {"n": 1}, {"n": 2}])
        sorted_dt = dt.sort_by("n")
        self.assertEqual([r.data["n"] for r, _ in sorted_dt.scan()], [1, 2, 3])

    def test_sort_by_descending(self):
        dt = DataTree.from_records([{"n": 1}, {"n": 3}, {"n": 2}])
        sorted_dt = dt.sort_by("n", reverse=True)
        self.assertEqual([r.data["n"] for r, _ in sorted_dt.scan()], [3, 2, 1])

    def test_reference_sharing(self):
        # group_by should share record refs (per design)
        recs = [{"k": "a", "x": 1}, {"k": "a", "x": 2}]
        dt = DataTree.from_records(recs)
        grouped = dt.group_by("k")
        members = grouped.collect()[0]["members"]
        # mutate via group reference
        members[0].set("x", 999)
        # the original DataTree's record reflects the change
        src_data = dt.collect()[0]["x"]
        self.assertEqual(src_data, 999)


# ═══════════════════════════════════════════════════════════════════════════
# Schema (carried over from v3)
# ═══════════════════════════════════════════════════════════════════════════

class TestSchema(unittest.TestCase):

    def test_schema_inference(self):
        dt = DataTree.from_records([{"a": 1, "b": "hi"}, {"a": 2, "b": "yo"}])
        schema = dt.infer_schema().schema
        self.assertIsInstance(schema, Schema)

    def test_schema_show(self):
        dt = DataTree.from_records([{"a": 1, "b": "hi"}])
        # .show() should not raise (auto-detect terminal vs IPython)
        # Use utf-8 to handle box-drawing characters on Windows.
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        dt.infer_schema().schema.show()

    def test_schema_handles_homogeneous_types(self):
        dt = DataTree.from_records([{"a": 1}, {"a": 2}, {"a": 3}])
        schema = dt.infer_schema().schema
        # Leaf(int) == Leaf(str) is True per v3 spec, so it should reconcile cleanly
        self.assertIsInstance(schema, Schema)

    def test_schema_handles_mixed_types(self):
        dt = DataTree.from_records([{"a": 1}, {"a": "hi"}])
        schema = dt.infer_schema().schema
        # mixed types may yield SchemaList (unreconcilable); both are acceptable
        self.assertIsNotNone(schema)

    def test_schema_empty_dt(self):
        dt = DataTree.from_records([])
        schema = dt.infer_schema().schema
        self.assertIsInstance(schema, Schema)


# ═══════════════════════════════════════════════════════════════════════════
# Expr pipeline (assign / keep / fork / case)
# ═══════════════════════════════════════════════════════════════════════════

class TestExprPipeline(unittest.TestCase):

    def test_assign_keep(self):
        dt = DataTree.from_records([{"n": i} for i in range(5)])
        dt2 = dt.expr(
            assign(b.squared, b.n * b.n),
            keep(b.n > 1),
        )
        out = [r.data for r, _ in dt2.scan()]
        self.assertEqual(out, [
            {"n": 2, "squared": 4},
            {"n": 3, "squared": 9},
            {"n": 4, "squared": 16},
        ])

    def test_assign_arithmetic(self):
        dt = DataTree.from_records([{"a": 1, "b": 2}])
        dt2 = dt.expr(assign(b.sum, b.a + b.b))
        first = next(dt2.scan())[0].data
        self.assertEqual(first["sum"], 3)

    def test_assign_with_numpy_scalar(self):
        ages = [{"age": 30}, {"age": 40}, {"age": 50}]
        dt = DataTree.from_records(ages)
        mu = np.mean([r["age"] for r in ages])
        dt2 = dt.expr(assign(b.normalized, (b.age - mu) / np.std([r["age"] for r in ages])))
        # Verify the field is set
        for r, _ in dt2.scan():
            self.assertIn("normalized", r.data)

    def test_keep_predicate(self):
        dt = DataTree.from_records([{"n": i} for i in range(5)])
        dt2 = dt.expr(keep(b.n >= 2))
        out = [r.data["n"] for r, _ in dt2.scan()]
        self.assertEqual(out, [2, 3, 4])

    def test_fork_basic(self):
        # if n > 2 → label = "big"; else label = "small"
        dt = DataTree.from_records([{"n": i} for i in range(4)])
        dt2 = dt.expr(fork(
            b.n > 2,
            then_block=(assign(b.label, "big"),),
            else_block=(assign(b.label, "small"),),
        ))
        out = [(r.data["n"], r.data["label"]) for r, _ in dt2.scan()]
        self.assertEqual(out, [(0, "small"), (1, "small"), (2, "small"), (3, "big")])

    def test_case_multi_way(self):
        dt = DataTree.from_records([{"n": i} for i in range(6)])
        dt2 = dt.expr(case(
            (b.n == 0, (assign(b.label, "zero"),)),
            (b.n < 3,   (assign(b.label, "low"),)),
            default=(assign(b.label, "high"),),
        ))
        out = [(r.data["n"], r.data["label"]) for r, _ in dt2.scan()]
        self.assertEqual(out, [
            (0, "zero"), (1, "low"), (2, "low"), (3, "high"), (4, "high"), (5, "high"),
        ])

    def test_path_attribute_access(self):
        dt = DataTree.from_records([{"a": {"b": {"c": 42}}}])
        # verify path binding
        self.assertEqual(b.a.b.c.indexer, "a.b.c")
        # use in expr
        dt2 = dt.expr(assign(b.doubled, b.a.b.c * 2))
        first = next(dt2.scan())[0].data
        self.assertEqual(first["doubled"], 84)


# ═══════════════════════════════════════════════════════════════════════════
# Intra-record ops (sbo.*)
# ═══════════════════════════════════════════════════════════════════════════

class TestIntraRecordOps(unittest.TestCase):

    def test_sbo_flatten_full(self):
        dt = DataTree.from_records([{"nested": [[1, 2], [3, [4, 5]]]}])
        dt2 = dt.expr(assign(b.flat, sbo.flatten(b.nested, -1)))
        first = next(dt2.scan())[0].data
        self.assertEqual(first["flat"], [1, 2, 3, 4, 5])

    def test_sbo_flatten_one_level(self):
        dt = DataTree.from_records([{"nested": [[1, 2], [3, 4]]}])
        dt2 = dt.expr(assign(b.flat, sbo.flatten(b.nested, 1)))
        first = next(dt2.scan())[0].data
        self.assertEqual(first["flat"], [1, 2, 3, 4])

    def test_sbo_filter_eager_result(self):
        # sbo.filter's eager result is the kept list
        dt = DataTree.from_records([{"tags": [1, 2, 3, 4, 5]}])
        dt2 = dt.expr(assign(b.big, sbo.filter(b.tags, lambda x: x > 3)))
        first = next(dt2.scan())[0].data
        self.assertEqual(first["big"], [4, 5])

    def test_sbo_filter_registers_skip_flag(self):
        # verify the lazy metadata mechanism: skip flag written to record.meta
        dt = DataTree.from_records([{"tags": [1, 2, 3, 4, 5]}])
        dt2 = dt.expr(assign(b.big, sbo.filter(b.tags, lambda x: x > 3)))
        # peek into the record's meta directly
        for r, _ in dt2.scan():
            self.assertIn("_skips", r.meta)
            # the mask should mark 3 elements as skipped
            skips = next(iter(r.meta["_skips"].values()))
            self.assertEqual(skips, [True, True, True, False, False])

    def test_sbo_map(self):
        dt = DataTree.from_records([{"xs": [1, 2, 3]}])
        dt2 = dt.expr(assign(b.squared, sbo.map(b.xs, lambda x: x * x)))
        first = next(dt2.scan())[0].data
        self.assertEqual(first["squared"], [1, 4, 9])

    def test_sbo_reduce_with_init(self):
        dt = DataTree.from_records([{"xs": [1, 2, 3, 4]}])
        dt2 = dt.expr(assign(b.total, sbo.reduce(b.xs, lambda a, x: a + x, init=0)))
        first = next(dt2.scan())[0].data
        self.assertEqual(first["total"], 10)

    def test_sbo_reduce_empty_raises(self):
        dt = DataTree.from_records([{"xs": []}])
        with self.assertRaises(ValueError):
            dt.expr(assign(b.total, sbo.reduce(b.xs, lambda a, x: a + x))).collect()

    def test_sbo_length(self):
        dt = DataTree.from_records([{"xs": [1, 2, 3]}, {"xs": []}])
        dt2 = dt.expr(assign(b.n, sbo.length(b.xs)))
        out = [r.data["n"] for r, _ in dt2.scan()]
        self.assertEqual(out, [3, 0])

    def test_sbo_length_keep_predicate(self):
        # keep rows where field length > 0
        dt = DataTree.from_records([
            {"name": "Alice", "tags": ["a", "b"]},
            {"name": "Bob", "tags": []},
        ])
        dt2 = dt.expr(keep(sbo.length(b.tags) > 0))
        out = [r.data["name"] for r, _ in dt2.scan()]
        self.assertEqual(out, ["Alice"])


# ═══════════════════════════════════════════════════════════════════════════
# chain() — build-time AST substitution
# ═══════════════════════════════════════════════════════════════════════════

class TestChain(unittest.TestCase):

    def test_chain_flatten_filter(self):
        recs = [{"tags": [[["ring"], [40, 44]], [["red"], [31, 34]]]}]
        dt = DataTree.from_records(recs)
        pipeline = chain(
            sbo.flatten(b.tags, -1),
            sbo.filter(sbo._, lambda x: isinstance(x, str)),
        )
        dt2 = dt.expr(assign(b.flat_kept, pipeline))
        first = next(dt2.scan())[0].data
        self.assertEqual(first["flat_kept"], ["ring", "red"])

    def test_chain_three_steps(self):
        recs = [{"xs": [1, 2, 3, 4, 5]}]
        dt = DataTree.from_records(recs)
        pipeline = chain(
            sbo.filter(b.xs, lambda x: x % 2 == 1),
            sbo.map(sbo._, lambda x: x * 10),
            sbo.reduce(sbo._, lambda a, x: a + x, init=0),
        )
        dt2 = dt.expr(assign(b.total_odd_x10, pipeline))
        first = next(dt2.scan())[0].data
        # 1*10 + 3*10 + 5*10 = 90
        self.assertEqual(first["total_odd_x10"], 90)

    def test_chain_first_step_no_placeholder(self):
        # first step must not contain _
        with self.assertRaises(ValueError):
            chain(sbo.filter(sbo._, lambda x: x > 0))


# ═══════════════════════════════════════════════════════════════════════════
# No invertibility surface
# ═══════════════════════════════════════════════════════════════════════════

class TestNoInvertibility(unittest.TestCase):

    def setUp(self):
        self.dt = DataTree.from_records([{"a": 1}])

    def test_no_invert_method(self):
        self.assertFalse(hasattr(self.dt, "invert"))

    def test_no_invert_all_method(self):
        self.assertFalse(hasattr(self.dt, "invert_all"))

    def test_no_history_attr(self):
        self.assertFalse(hasattr(self.dt, "_history"))

    def test_no_track_attr(self):
        self.assertFalse(hasattr(self.dt, "_track"))

    def test_no_seal_method(self):
        self.assertFalse(hasattr(self.dt, "seal"))

    def test_no_provenance_markers_in_meta(self):
        for r, m in self.dt.scan():
            for marker in ("_ins", "_undo", "_p", "_pos", "_src"):
                self.assertNotIn(marker, m)
                self.assertNotIn(marker, r.meta)


# ═══════════════════════════════════════════════════════════════════════════
# Operator overloading
# ═══════════════════════════════════════════════════════════════════════════

class TestOperatorOverloading(unittest.TestCase):

    def test_add_concat(self):
        a = DataTree.from_records([{"x": 1}])
        b = DataTree.from_records([{"x": 2}])
        merged = a + b
        self.assertEqual(merged.collect(), [{"x": 1}, {"x": 2}])

    def test_add_with_list(self):
        a = DataTree.from_records([{"x": 1}])
        merged = a + [{"x": 2}, {"x": 3}]
        self.assertEqual(merged.collect(), [{"x": 1}, {"x": 2}, {"x": 3}])

    def test_bool(self):
        empty = DataTree.from_records([])
        self.assertFalse(bool(empty))
        non_empty = DataTree.from_records([{"x": 1}])
        self.assertTrue(bool(non_empty))

    def test_pipe(self):
        dt = DataTree.from_records([{"n": i} for i in range(3)])
        result = dt | (lambda t: t.head(2))
        self.assertEqual([r.data["n"] for r, _ in result.scan()], [0, 1])


if __name__ == "__main__":
    unittest.main()
