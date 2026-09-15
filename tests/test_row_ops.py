"""test_row_ops.py — tests for row-wise 1→1 expr statement ops.

Covers:
- Structural ops: rename, drop, copy_field, default, nest, unnest
- Conditional ops: assert_, mask
- Sugar ops: cast, upper, lower_str, trim, round_field, coalesce
- Integration: chaining multiple ops, fork/case interactions, Program compatibility
"""
import os
import shutil
import unittest

from sunbear import DataTree, Program
from sunbear.expr import (
    b, assign, keep,
    rename, drop, copy_field, default, nest, unnest,
    assert_, mask, cast, upper, lower_str, trim, round_field, coalesce,
    select, sbo,
)


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _sample_dt():
    return DataTree.from_records([
        {"name": "Alice", "age": 30, "score": 85.123,
         "tags": ["a", "b"],
         "address": {"city": "NY", "zip": "10001"},
         "nickname": None},
        {"name": "Bob", "age": 17, "score": 42.567,
         "tags": ["c"],
         "address": {"city": "LA", "zip": "90001"},
         "nickname": "Bobby"},
    ])


_CACHE_DIR = ".sunbear_cache"


# ═══════════════════════════════════════════════════════════════════════════
# Structural ops
# ═══════════════════════════════════════════════════════════════════════════

class TestRename(unittest.TestCase):

    def test_single_rename(self):
        dt = _sample_dt()
        r = dt.expr(*rename(name="full_name"))
        rows = r.collect()
        for row in rows:
            self.assertIn("full_name", row)
            self.assertNotIn("name", row)
        self.assertEqual([row["full_name"] for row in rows], ["Alice", "Bob"])

    def test_multi_rename(self):
        dt = _sample_dt()
        r = dt.expr(*rename(name="full_name", age="years"))
        rows = r.collect()
        for row in rows:
            self.assertIn("full_name", row)
            self.assertIn("years", row)
            self.assertNotIn("name", row)
            self.assertNotIn("age", row)

    def test_rename_nonexistent_is_noop(self):
        dt = _sample_dt()
        r = dt.expr(*rename(bogus="new_field"))
        rows = r.collect()
        # Should not crash; rows unchanged except no "new_field" with a value
        self.assertEqual(len(rows), 2)


class TestDrop(unittest.TestCase):

    def test_single_drop(self):
        dt = _sample_dt()
        r = dt.expr(drop(b.tags))
        for row in r.collect():
            self.assertNotIn("tags", row)
            self.assertIn("name", row)

    def test_multi_drop(self):
        dt = _sample_dt()
        r = dt.expr(drop(b.tags, b.address))
        for row in r.collect():
            self.assertNotIn("tags", row)
            self.assertNotIn("address", row)
            self.assertIn("name", row)

    def test_drop_all(self):
        dt = DataTree.from_records([{"x": 1, "y": 2}])
        r = dt.expr(drop(b.x, b.y))
        self.assertEqual(r.collect(), [{}])


class TestCopyField(unittest.TestCase):

    def test_copy(self):
        dt = _sample_dt()
        r = dt.expr(copy_field(b.name, b.backup))
        for row in r.collect():
            self.assertEqual(row["name"], row["backup"])

    def test_copy_preserves_original(self):
        dt = _sample_dt()
        r = dt.expr(copy_field(b.name, b.backup))
        for row in r.collect():
            self.assertIn("name", row)
            self.assertIn("backup", row)


class TestDefault(unittest.TestCase):

    def test_default_sets_missing(self):
        dt = _sample_dt()
        r = dt.expr(default(b.nickname, "anon"))
        rows = r.collect()
        # Alice: nickname was None → should get "anon"
        self.assertEqual(rows[0]["nickname"], "anon")
        # Bob: nickname was "Bobby" → should stay "Bobby"
        self.assertEqual(rows[1]["nickname"], "Bobby")

    def test_default_does_not_overwrite(self):
        dt = DataTree.from_records([{"x": 10}, {"x": None}])
        r = dt.expr(default(b.x, 99))
        rows = r.collect()
        self.assertEqual(rows[0]["x"], 10)
        self.assertEqual(rows[1]["x"], 99)


class TestNest(unittest.TestCase):

    def test_nest_fields(self):
        dt = _sample_dt()
        r = dt.expr(nest(b.name, b.age, into="info"))
        rows = r.collect()
        for row in rows:
            self.assertNotIn("name", row)
            self.assertNotIn("age", row)
            self.assertIn("info", row)
            self.assertIn("name", row["info"])
            self.assertIn("age", row["info"])
        self.assertEqual(rows[0]["info"]["name"], "Alice")
        self.assertEqual(rows[0]["info"]["age"], 30)


class TestUnnest(unittest.TestCase):

    def test_unnest(self):
        dt = _sample_dt()
        r = dt.expr(unnest(b.address))
        rows = r.collect()
        for row in rows:
            self.assertNotIn("address", row)
            self.assertIn("city", row)
            self.assertIn("zip", row)
        self.assertEqual(rows[0]["city"], "NY")
        self.assertEqual(rows[1]["city"], "LA")

    def test_unnest_non_dict_is_noop(self):
        dt = DataTree.from_records([{"x": 42}])
        r = dt.expr(unnest(b.x))
        rows = r.collect()
        # Non-dict values should pass through unchanged
        self.assertEqual(rows[0]["x"], 42)


# ═══════════════════════════════════════════════════════════════════════════
# Conditional ops
# ═══════════════════════════════════════════════════════════════════════════

class TestAssert(unittest.TestCase):

    def test_assert_raises_with_default_message(self):
        dt = _sample_dt()
        r = dt.expr(assert_(b.age >= 18))
        with self.assertRaisesRegex(ValueError, "SunBear assertion failed"):
            r.collect()

    def test_assert_passes_all(self):
        dt = _sample_dt()
        r = dt.expr(assert_(b.age >= 0))
        self.assertEqual(len(r.collect()), 2)

    def test_assert_raises_on_first_failure(self):
        dt = _sample_dt()
        r = dt.expr(assert_(b.age >= 100))
        with self.assertRaisesRegex(ValueError, "SunBear assertion failed"):
            r.collect()

    def test_assert_with_message(self):
        dt = _sample_dt()
        r = dt.expr(assert_(b.age >= 18, "too young"))
        with self.assertRaises(ValueError) as ctx:
            r.collect()
        self.assertIn("too young", str(ctx.exception))


class TestMask(unittest.TestCase):

    def test_mask_sets_on_match(self):
        dt = _sample_dt()
        r = dt.expr(mask(b.flag, b.age < 18, "minor"))
        rows = r.collect()
        # Alice: age 30, not < 18 → flag stays None
        self.assertIsNone(rows[0].get("flag"))
        # Bob: age 17, < 18 → flag = "minor"
        self.assertEqual(rows[1]["flag"], "minor")

    def test_mask_all_match(self):
        dt = DataTree.from_records([{"x": 1}, {"x": 2}])
        r = dt.expr(mask(b.y, b.x > 0, "positive"))
        rows = r.collect()
        self.assertEqual(rows[0]["y"], "positive")
        self.assertEqual(rows[1]["y"], "positive")

    def test_mask_none_match(self):
        dt = DataTree.from_records([{"x": 1}, {"x": 2}])
        r = dt.expr(mask(b.y, b.x > 10, "big"))
        rows = r.collect()
        self.assertIsNone(rows[0].get("y"))
        self.assertIsNone(rows[1].get("y"))


# ═══════════════════════════════════════════════════════════════════════════
# Sugar ops
# ═══════════════════════════════════════════════════════════════════════════

class TestCast(unittest.TestCase):

    def test_cast_to_str(self):
        dt = _sample_dt()
        r = dt.expr(cast(b.age, str))
        rows = r.collect()
        for row in rows:
            self.assertIsInstance(row["age"], str)

    def test_cast_to_int(self):
        dt = DataTree.from_records([{"x": "42"}, {"x": "7"}])
        r = dt.expr(cast(b.x, int))
        rows = r.collect()
        self.assertEqual(rows[0]["x"], 42)
        self.assertIsInstance(rows[0]["x"], int)


class TestUpper(unittest.TestCase):

    def test_upper(self):
        dt = _sample_dt()
        r = dt.expr(upper(b.name))
        names = [row["name"] for row in r.collect()]
        self.assertEqual(names, ["ALICE", "BOB"])


class TestLowerStr(unittest.TestCase):

    def test_lower(self):
        dt = DataTree.from_records([{"x": "HELLO"}, {"x": "World"}])
        r = dt.expr(lower_str(b.x))
        vals = [row["x"] for row in r.collect()]
        self.assertEqual(vals, ["hello", "world"])


class TestTrim(unittest.TestCase):

    def test_trim(self):
        dt = DataTree.from_records([{"x": "  hello  "}, {"x": "world "}])
        r = dt.expr(trim(b.x))
        vals = [row["x"] for row in r.collect()]
        self.assertEqual(vals, ["hello", "world"])


class TestRoundField(unittest.TestCase):

    def test_round_default(self):
        dt = DataTree.from_records([{"x": 1.555}, {"x": 2.444}])
        r = dt.expr(round_field(b.x))
        vals = [row["x"] for row in r.collect()]
        self.assertEqual(vals, [2, 2])

    def test_round_digits(self):
        dt = _sample_dt()
        r = dt.expr(round_field(b.score, 1))
        vals = [row["score"] for row in r.collect()]
        self.assertEqual(vals, [85.1, 42.6])


class TestCoalesce(unittest.TestCase):

    def test_coalesce_picks_first_non_none(self):
        dt = _sample_dt()
        r = dt.expr(coalesce(b.nickname, b.name, target=b.display))
        rows = r.collect()
        # Alice: nickname is None → picks name
        self.assertEqual(rows[0]["display"], "Alice")
        # Bob: nickname is "Bobby" → picks nickname
        self.assertEqual(rows[1]["display"], "Bobby")

    def test_coalesce_all_none(self):
        dt = DataTree.from_records([{"a": None, "b": None}])
        r = dt.expr(coalesce(b.a, b.b, target=b.c))
        rows = r.collect()
        # All None → target not set
        self.assertNotIn("c", rows[0])


# ═══════════════════════════════════════════════════════════════════════════
# Integration: chaining + Program
# ═══════════════════════════════════════════════════════════════════════════

class TestIntegration(unittest.TestCase):

    def test_rename_then_keep(self):
        dt = _sample_dt()
        r = dt.expr(
            *rename(name="full_name"),
            keep(b.age >= 18),
        )
        rows = r.collect()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["full_name"], "Alice")

    def test_select_then_upper(self):
        dt = _sample_dt()
        r = dt.expr(
            *select(b.name, b.age),
            upper(b.name),
        )
        rows = r.collect()
        for row in rows:
            self.assertEqual(set(row.keys()), {"name", "age"})
        self.assertEqual(rows[0]["name"], "ALICE")

    def test_unnest_then_drop(self):
        dt = _sample_dt()
        r = dt.expr(
            unnest(b.address),
            drop(b.zip),
        )
        rows = r.collect()
        for row in rows:
            self.assertNotIn("address", row)
            self.assertNotIn("zip", row)
            self.assertIn("city", row)

    def test_default_then_assert(self):
        dt = DataTree.from_records([
            {"name": "Alice", "score": None},
            {"name": "Bob", "score": 85},
        ])
        r = dt.expr(
            default(b.score, 0),
            assert_(b.score >= 50),
        )
        with self.assertRaisesRegex(ValueError, "SunBear assertion failed"):
            r.collect()

    def test_nest_then_unnest_roundtrip(self):
        dt = _sample_dt()
        r = dt.expr(
            nest(b.name, b.age, into="info"),
            unnest(b.info),
        )
        rows = r.collect()
        for row in rows:
            self.assertIn("name", row)
            self.assertIn("age", row)
            self.assertNotIn("info", row)
        self.assertEqual(rows[0]["name"], "Alice")

    def test_assign_then_drop(self):
        dt = _sample_dt()
        r = dt.expr(
            assign(b.tier, "standard"),
            drop(b.tags, b.address),
        )
        rows = r.collect()
        for row in rows:
            self.assertNotIn("tags", row)
            self.assertNotIn("address", row)
            self.assertEqual(row["tier"], "standard")

    def test_coalesce_then_select(self):
        dt = _sample_dt()
        r = dt.expr(
            coalesce(b.nickname, b.name, target=b.display),
            *select(b.display, b.age),
        )
        rows = r.collect()
        for row in rows:
            self.assertEqual(set(row.keys()), {"display", "age"})
        self.assertEqual(rows[0]["display"], "Alice")
        self.assertEqual(rows[1]["display"], "Bobby")

    def test_mask_then_keep(self):
        dt = DataTree.from_records([
            {"x": 5}, {"x": 15}, {"x": 25},
        ])
        r = dt.expr(
            mask(b.label, b.x < 10, "low"),
            keep(b.label.is_not_null()),
        )
        rows = r.collect()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["label"], "low")


class TestProgramCompatibility(unittest.TestCase):
    """Ensure all new ops work inside Program (row-based caching)."""

    def setUp(self):
        if os.path.exists(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)

    def tearDown(self):
        if os.path.exists(_CACHE_DIR):
            shutil.rmtree(_CACHE_DIR)

    def test_program_with_rename(self):
        dt = _sample_dt()
        prog = Program(name="t_rename").expr(
            *rename(name="full_name"),
        )
        r = prog(dt)
        self.assertEqual([row["full_name"] for row in r.collect()], ["Alice", "Bob"])
        # Cache hit
        r2 = prog(dt)
        self.assertEqual([row["full_name"] for row in r2.collect()], ["Alice", "Bob"])

    def test_program_with_drop(self):
        dt = _sample_dt()
        prog = Program(name="t_drop").expr(
            drop(b.tags, b.address),
            keep(b.age >= 18),
        )
        rows = prog(dt).collect()
        self.assertEqual(len(rows), 1)
        self.assertNotIn("tags", rows[0])

    def test_program_with_assert(self):
        dt = _sample_dt()
        prog = Program(name="t_assert").expr(
            assert_(b.age >= 18),
        )
        with self.assertRaisesRegex(ValueError, "SunBear assertion failed"):
            prog(dt).collect()

    def test_program_with_sugar_ops(self):
        dt = _sample_dt()
        prog = Program(name="t_sugar").expr(
            upper(b.name),
            round_field(b.score, 0),
        )
        rows = prog(dt).collect()
        self.assertEqual(rows[0]["name"], "ALICE")
        self.assertEqual(rows[0]["score"], 85)

    def test_program_full_pipeline(self):
        dt = _sample_dt()
        prog = Program(name="t_full").expr(
            unnest(b.address),
            coalesce(b.nickname, b.name, target=b.display),
            *select(b.display, b.city, b.score),
            round_field(b.score, 0),
            upper(b.city),
            keep(b.score >= 50),
        )
        rows = prog(dt).collect()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["display"], "Alice")
        self.assertEqual(row["city"], "NY")
        self.assertEqual(row["score"], 85)
        self.assertEqual(set(row.keys()), {"display", "city", "score"})


if __name__ == "__main__":
    unittest.main()
