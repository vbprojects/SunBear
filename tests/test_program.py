"""test_program.py — tests for Program (expr-only, row-based caching).

Covers:
- Program construction and repr
- Expr pipeline (assign, keep, combined)
- Pipe syntax (dt | prog)
- Row-based cache: hit, miss, mixed, filtered rows
- FileCache persistence and to_DataTree() round-trip
- Custom cache name vs auto-hash
- Input immutability
"""
import os
import shutil
import unittest

from sunbear import DataTree, Program, FileCache
from sunbear.expr import b, assign, keep


# ═══════════════════════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════════════════════

def _sample_dt():
    return DataTree.from_records([
        {"name": "Alice", "age": 30, "score": 85},
        {"name": "Bob",   "age": 17, "score": 42},
        {"name": "Carol", "age": 25, "score": 91},
    ])


_CACHE_DIR = ".sunbear_cache"


# ═══════════════════════════════════════════════════════════════════════════
# Construction & repr
# ═══════════════════════════════════════════════════════════════════════════

class TestConstruction(unittest.TestCase):

    def test_empty_repr(self):
        prog = Program()
        self.assertIn("Program(", repr(prog))
        self.assertIn("0 stmts", repr(prog))

    def test_expr_repr(self):
        prog = Program(name="test").expr(assign(b.status, "ok"))
        self.assertIn("'test'", repr(prog))
        self.assertIn("1 stmts", repr(prog))

    def test_auto_name(self):
        prog = Program().expr(assign(b.x, 1))
        self.assertIn("<auto>", repr(prog))


# ═══════════════════════════════════════════════════════════════════════════
# Expr pipeline
# ═══════════════════════════════════════════════════════════════════════════

class TestExprPipeline(unittest.TestCase):

    def test_assign(self):
        dt = _sample_dt()
        prog = Program(name="t_assign").expr(assign(b.status, "active"))
        result = prog(dt)
        for row in result.collect():
            self.assertEqual(row["status"], "active")
        self.assertEqual(len(result), 3)

    def test_keep_filters_rows(self):
        dt = _sample_dt()
        prog = Program(name="t_keep").expr(keep(b.age >= 18))
        result = prog(dt)
        names = [r["name"] for r in result.collect()]
        self.assertEqual(names, ["Alice", "Carol"])

    def test_assign_and_keep(self):
        dt = _sample_dt()
        prog = Program(name="t_combo").expr(
            assign(b.tier, "standard"),
            keep(b.score > 50),
        )
        result = prog(dt)
        rows = result.collect()
        self.assertEqual(len(rows), 2)
        for row in rows:
            self.assertEqual(row["tier"], "standard")
            self.assertGreater(row["score"], 50)

    def test_computation(self):
        dt = _sample_dt()
        prog = Program(name="t_math").expr(assign(b.half, b.score / 2))
        result = prog(dt)
        halves = [r["half"] for r in result.collect()]
        self.assertEqual(halves, [42.5, 21.0, 45.5])

    def test_pipe_syntax(self):
        dt = _sample_dt()
        prog = Program(name="t_pipe").expr(assign(b.ok, True))
        result = dt | prog
        for row in result.collect():
            self.assertTrue(row["ok"])


# ═══════════════════════════════════════════════════════════════════════════
# Row-based caching
# ═══════════════════════════════════════════════════════════════════════════

class TestRowCache(unittest.TestCase):

    def setUp(self):
        if os.path.exists(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)

    def tearDown(self):
        if os.path.exists(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)

    def test_cache_hit_same_data(self):
        dt = _sample_dt()
        prog = Program(name="hit").expr(assign(b.status, "ok"))
        r1 = prog(dt)
        r2 = prog(dt)
        self.assertEqual(r1.collect(), r2.collect())

    def test_cache_miss_new_row(self):
        """Add a new row between calls — it should be computed, not skipped."""
        dt1 = DataTree.from_records([{"x": 1}, {"x": 2}])
        prog = Program(name="miss").expr(assign(b.tag, "v"))
        r1 = prog(dt1)
        self.assertEqual(len(r1), 2)

        dt2 = DataTree.from_records([{"x": 1}, {"x": 2}, {"x": 3}])
        r2 = prog(dt2)
        self.assertEqual(len(r2), 3)
        tags = [r["tag"] for r in r2.collect()]
        self.assertEqual(tags, ["v", "v", "v"])

    def test_filtered_rows_cached(self):
        dt = _sample_dt()
        prog = Program(name="filt").expr(keep(b.age >= 18))
        r1 = prog(dt)
        self.assertEqual(len(r1), 2)
        # Second call: Bob still filtered, Alice & Carol still pass
        r2 = prog(dt)
        self.assertEqual(len(r2), 2)
        names = [r["name"] for r in r2.collect()]
        self.assertEqual(names, ["Alice", "Carol"])

    def test_filecache_persists(self):
        dt = _sample_dt()
        prog = Program(name="persist").expr(assign(b.z, 99))
        prog(dt)
        # New program with same name — should load existing cache
        prog2 = Program(name="persist").expr(assign(b.z, 99))
        r2 = prog2(dt)
        for row in r2.collect():
            self.assertEqual(row["z"], 99)


# ═══════════════════════════════════════════════════════════════════════════
# to_DataTree
# ═══════════════════════════════════════════════════════════════════════════

class TestToDataTree(unittest.TestCase):

    def setUp(self):
        if os.path.exists(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)

    def tearDown(self):
        if os.path.exists(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)

    def test_round_trip(self):
        dt = _sample_dt()
        prog = Program(name="rt").expr(assign(b.status, "ok"))
        prog(dt)
        loaded = prog.to_DataTree()
        self.assertEqual(len(loaded), 3)
        for row in loaded.collect():
            self.assertEqual(row["status"], "ok")

    def test_no_cache_raises(self):
        prog = Program()
        with self.assertRaises(RuntimeError):
            prog.to_DataTree()

    def test_empty_cache_raises(self):
        prog = Program(name="empty")
        # Never called — cache is empty (file not even created)
        with self.assertRaises(RuntimeError):
            prog.to_DataTree()


# ═══════════════════════════════════════════════════════════════════════════
# Custom cache
# ═══════════════════════════════════════════════════════════════════════════

class TestCustomCache(unittest.TestCase):

    def setUp(self):
        if os.path.exists(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)

    def tearDown(self):
        if os.path.exists(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)

    def test_explicit_filecache(self):
        dt = _sample_dt()
        cache = FileCache("my_prog")
        prog = Program(cache=cache).expr(assign(b.x, 1))
        prog(dt)
        self.assertTrue(os.path.exists(os.path.join(_CACHE_DIR, "my_prog.json")))

    def test_custom_name_creates_default_cache(self):
        dt = _sample_dt()
        prog = Program(name="custom").expr(assign(b.x, 1))
        prog(dt)
        self.assertTrue(os.path.exists(os.path.join(_CACHE_DIR, "custom.json")))


# ═══════════════════════════════════════════════════════════════════════════
# Input immutability
# ═══════════════════════════════════════════════════════════════════════════

class TestImmutability(unittest.TestCase):

    def test_input_not_mutated(self):
        dt = _sample_dt()
        original = dt.collect()
        prog = Program(name="immut").expr(
            assign(b.status, "ok"),
            keep(b.age >= 18),
        )
        prog(dt)
        self.assertEqual(dt.collect(), original)


if __name__ == "__main__":
    unittest.main()
