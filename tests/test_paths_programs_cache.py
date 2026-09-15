import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from sunbear import (DataTree, Record, Program, FileCache, MISSING,
                     TransformationError, write_jsonl, read_jsonl)
from sunbear.expr import b, assign, keep, fork, case, select, drop, nest, unnest, sbo


class TestStructuredPaths(unittest.TestCase):
    def test_literal_and_index_paths(self):
        r = Record({"literal.key": {"items": [{"price": None}, {"price": 7}]}, "exists": 42})
        self.assertEqual(r.get(b["exists"]), 42)
        self.assertIsNone(r.get(b["literal.key"].items[0].price))
        self.assertEqual(r.get(b["literal.key"].items[-1].price), 7)
        self.assertIs(r.get(b["literal.key"].items[8], MISSING), MISSING)
        with self.assertRaises(IndexError):
            r.set(b["literal.key"].items[8], 2)

    def test_null_missing_empty_traversal(self):
        r = Record({"items": [{"x": None}, {}, {"x": []}, {"x": [None]}], "empty": []})
        self.assertEqual(r.get(b.items.x), [None, [], [None]])
        self.assertEqual(r.get(b.items[...].x), [None, [], [None]])
        self.assertEqual(r.get(b.empty.x), [])
        r.mv(b.items[0].x, b["null.value"])
        self.assertIn("null.value", r.data)
        self.assertIsNone(r.data["null.value"])

    def test_missing_expressions(self):
        tree = DataTree.from_records([{}, {"x": None}, {"x": []}, {"x": [None]}])
        rows = tree.expr(select(exists=b.x.exists(), null=b.x.is_null(),
                                filled=b.x.fill_missing(10))).collect()
        self.assertEqual(rows, [
            {"exists": False, "null": False, "filled": 10},
            {"exists": True, "null": True, "filled": None},
            {"exists": True, "null": False, "filled": []},
            {"exists": True, "null": False, "filled": [None]}])
        self.assertEqual(tree.expr(select(x=b.missing)).collect(), [{}, {}, {}, {}])

    def test_guard_short_circuits(self):
        rows = DataTree.from_records([{}, {"x": 2}]).expr(
            keep(b.x.exists() & (b.x > 1))).collect()
        self.assertEqual(rows, [{"x": 2}])

    def test_nested_output_missing(self):
        r = Record({})
        r.set("x", {"missing": MISSING, "null": None})
        self.assertEqual(r.data, {"x": {"null": None}})
        with self.assertRaises(ValueError):
            r.set("bad", [MISSING])

    def test_deep_path_copy_and_siblings(self):
        original = {"a": {"b": [{"x": 1}]}, "untouched": {"large": []}}
        tree = DataTree.from_records([original])
        left = tree.expr(assign(b.a.b[0].x, 2))
        right = tree.set(b.a.b[0].x, 3)
        l, r = left.collect()[0], right.collect()[0]
        self.assertEqual(original["a"]["b"][0]["x"], 1)
        self.assertEqual((l["a"]["b"][0]["x"], r["a"]["b"][0]["x"]), (2, 3))
        self.assertIs(l["untouched"], original["untouched"])
        self.assertEqual(left.collect(), [l])

    def test_traversal_update_isolated(self):
        tree = DataTree.from_records([{"items": [{"x": 1}, {"x": 2}]}])
        result = tree.expr(assign(b.items[...].x, 9)).collect()
        self.assertEqual(result, [{"items": [{"x": 9}, {"x": 9}]}])
        self.assertEqual(tree.collect(), [{"items": [{"x": 1}, {"x": 2}]}])


class TestCompiledPrograms(unittest.TestCase):
    def test_branch_filters_and_nested_statements(self):
        p = Program().expr(fork(b.x > 0,
            [assign(y=b.x + 1), keep(b.x > 1)],
            [keep(False)]))
        source = DataTree.from_records([{"x": -1}, {"x": 1}, {"x": 2}])
        self.assertEqual(p(source).collect(), [{"x": 2, "y": 3}])
        self.assertEqual(p(source).collect(), [{"x": 2, "y": 3}])

    def test_case_nested_shape_operations(self):
        p = Program().expr(case((b.x > 0, [nest(b.x, into="box"), unnest(b.box), select(b.x)]),
                               default=[drop(b.x)]))
        self.assertEqual(p(DataTree.from_records([{"x": 1, "y": 2}, {"x": 0}])).collect(),
                         [{"x": 1}, {}])

    def test_validation_precedes_source_reads(self):
        reads = []
        def rows():
            reads.append(1)
            yield {}
        tree = DataTree.from_iter(rows())
        with self.assertRaises(TypeError):
            tree.expr(fork(True, [("sort", b.x)]))
        self.assertEqual(reads, [])

    def test_definition_is_owned_and_immutable(self):
        value = {"nested": [1]}
        stmt = assign(b.x, value)
        p = Program().expr(stmt)
        value["nested"].append(2)
        q = p.expr(assign(b.y, 3))
        stmt[2].value["nested"].append(4)
        rows = DataTree.from_records([{}])
        self.assertEqual(p(rows).collect(), [{"x": {"nested": [1]}}])
        self.assertEqual(q(rows).collect(), [{"x": {"nested": [1]}, "y": 3}])
        with self.assertRaises(AttributeError):
            p._name = "changed"

    def test_no_row_recompilation(self):
        p = Program().expr(assign(b.x, b.y + 1))
        with patch("sunbear.expr.lower.compile_plan", side_effect=AssertionError("recompiled")):
            self.assertEqual(len(p(DataTree.from_records([{"y": i} for i in range(10)])).collect()), 10)

    def test_context_and_original_cause(self):
        with self.assertRaises(TransformationError) as ctx:
            Program().expr(assign(b.x, b.y + 1))(DataTree.from_records([{"y": "private-value"}])).collect()
        self.assertEqual((ctx.exception.step, ctx.exception.row), (1, 0))
        self.assertIsInstance(ctx.exception.__cause__, TypeError)
        self.assertNotIn("private-value", str(ctx.exception))


class TestExplicitCaching(unittest.TestCase):
    def test_cached_callback_runs_once_and_duplicates_remain(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def callback(value):
                calls.append(value)
                return value + 1
            cache = FileCache("test", directory=directory)
            with self.assertRaises(ValueError):
                Program(cache=cache).expr(assign(b.y, sbo.map(b.x, callback)))
            p = Program(cache=cache, cache_version="v1").expr(assign(b.y, sbo.map(b.x, callback)))
            source = DataTree.from_records([{"x": [1]}, {"x": [1]}])
            expected = [{"x": [1], "y": [2]}, {"x": [1], "y": [2]}]
            self.assertEqual(p(source).collect(), expected)
            self.assertEqual(p(source).collect(), expected)
            self.assertEqual(calls, [1])
            reload = Program(cache=FileCache("test", directory=directory), cache_version="v1").expr(
                assign(b.y, sbo.map(b.x, callback)))
            self.assertEqual(reload(source).collect(), expected)
            self.assertEqual(calls, [1])

    def test_same_name_different_definition_and_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = FileCache("test", directory=directory)
            p = Program(cache=cache, name="same").expr(assign(b.x, 1))
            q = Program(cache=cache, name="same").expr(assign(b.x, 2))
            source = DataTree.from_records([{}])
            self.assertEqual(p(source).collect(), [{"x": 1}])
            self.assertEqual(q(source).collect(), [{"x": 2}])
            self.assertEqual(p.expr(assign(b.x, 3))(source).collect(), [{"x": 3}])
            self.assertEqual(p(source).collect(), [{"x": 1}])

    def test_strict_codec_and_batched_flush(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = FileCache("test", directory=directory, flush_every=10)
            cache.set("a", {"x": [1, None, True, 2.0]})
            self.assertFalse(Path(cache._path).exists())
            cache.flush()
            self.assertEqual(FileCache("test", directory=directory).get("a"), {"x": [1, None, True, 2.0]})
            for value in [(1, 2), {1: "x"}, float("nan"), MISSING]:
                with self.assertRaises(TypeError):
                    cache.set("bad", {"x": value})

    def test_cache_output_isolation_and_filter(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Program(cache=FileCache("test", directory=directory)).expr(keep(b.x > 0), assign(y=[1]))
            source = DataTree.from_records([{"x": 0}, {"x": 1}])
            first = p(source).collect()
            first[0]["y"].append(2)
            self.assertEqual(p(source).collect(), [{"x": 1, "y": [1]}])

    def test_saved_run_order_and_atomic_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.jsonl"
            rows = [{"x": 2}, {"x": 1}, {"x": 2}]
            write_jsonl(DataTree.from_records(rows), path)
            self.assertEqual(read_jsonl(path).collect(), rows)
            before = path.read_bytes()
            bad = DataTree.from_records([{"x": 1}, {"x": object()}])
            with self.assertRaises(TypeError):
                write_jsonl(bad, path)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

class TestCacheVersioning(unittest.TestCase):
    def test_version_change_reexecutes_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            def callback(value):
                calls.append(1)
                return value
            cache = FileCache("versions", directory=directory)
            source = DataTree.from_records([{"x": [1]}])
            for version in ["v1", "v1", "v2"]:
                Program(cache=cache, cache_version=version).expr(
                    assign(b.x, sbo.map(b.x, callback)))(source).collect()
            self.assertEqual(len(calls), 2)

    def test_named_program_does_not_create_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("sunbear.Program.FileCache", side_effect=AssertionError("implicit cache")):
                self.assertEqual(Program(name="label").expr(assign(x=1))(
                    DataTree.from_records([{}])).collect(), [{"x": 1}])

    def test_custom_registry_requires_version(self):
        from sunbear.expr import Call, register_func
        from sunbear.expr.eval import FUNCS
        with tempfile.TemporaryDirectory() as directory:
            register_func("custom_test", lambda v: v)
            try:
                with self.assertRaises(ValueError):
                    Program(cache=FileCache("custom", directory=directory)).expr(
                        assign(b.x, Call("custom_test", [b.x])))
            finally:
                FUNCS.pop("custom_test")

    def test_execution_failure_leaves_saved_run_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run.jsonl"
            write_jsonl(DataTree.from_records([{"ok": True}]), path)
            before = path.read_bytes()
            program = Program().expr(assign(b.y, b.x + 1))
            with self.assertRaises(TransformationError):
                write_jsonl(program(DataTree.from_records([{"x": 1}, {"x": None}])), path)
            self.assertEqual(path.read_bytes(), before)
