"""Spec example tests for sunbear.expr.

Each test mirrors a canonical example from the expr plan / expr_notes.md.
These guard against regression and document the intended API.
"""
import numpy as np
import unittest

from sunbear import DataTree
from sunbear.expr import (
    assign, keep, fork, case, map_assign,
    b, Sym, Symbols, as_indexer, _,
)
from sunbear.ops import (
    flatten, filter as ops_filter, map as ops_map, chain,
    length as sbo_length, size as sbo_size, count as sbo_count,
)


class TestSpecExample1Symbols(unittest.TestCase):
    """Spec example 1: Symbols-based column references and aggregations."""

    def setUp(self):
        self.records = [
            {"record": {"age": 30, "height": 170}},
            {"record": {"age": 25, "height": 165}},
            {"record": {"age": 40, "height": 180}},
            {"record": {"age": 35, "height": 175}},
        ]
        self.dt = DataTree.from_records(self.records)

    def test_normalize_with_symbols(self):
        age, height = Symbols("record.age", "record.height")
        ages, heights = self.dt.pluck(age), self.dt.pluck(height)
        mu_age, mu_height = np.mean(ages), np.mean(heights)
        std_age, std_height = np.std(ages), np.std(heights)

        dt2 = self.dt.expr(
            assign(Sym("record.standardized_age"), (age - mu_age) / std_age),
            assign(Sym("record.standardized_height"), (height - mu_height) / std_height),
            keep(Sym("record.standardized_age") < 2.0),
        )

        # All original ages < 2*std away from mean — so nothing is filtered out
        self.assertEqual(len(dt2), 4)
        # Round-trip
        self.assertEqual(dt2.invert_all().twigs, self.dt.twigs)


class TestSpecExample2LazyNamespace(unittest.TestCase):
    """Spec example 2: LazyNamespace (b) attribute-access path building."""

    def test_lazy_namespace_paths(self):
        # Verify path construction
        self.assertEqual(b.record.age.indexer, "record.age")
        self.assertEqual(b.profile.bio.height.indexer, "profile.bio.height")
        # Bracket fallback for non-identifier fields
        self.assertEqual(b["x y"].indexer, "x y")
        self.assertEqual(b["weird field"].indexer, "weird field")

    def test_aggregation_via_namespace(self):
        records = [
            {"name": "Alice", "age": 30, "height": 170},
            {"name": "Bob",   "age": 25, "height": 165},
            {"name": "Carol", "age": 40, "height": 180},
        ]
        dt = DataTree.from_records(records)

        ages = dt.pluck(b.age)
        mu, std = np.mean(ages), np.std(ages)

        dt2 = dt.expr(
            assign(b.s_age, (b.age - mu) / std),
        )
        # Verify the new field was set
        for r, _ in dt2.scan():
            self.assertIn("s_age", r.data)
        # Round-trip
        self.assertEqual(dt2.invert_all().twigs, dt.twigs)


class TestSpecTagsExample(unittest.TestCase):
    """Spec tags example: flatten + filter with chain."""

    def test_flatten_and_filter_chain(self):
        records = {
            "name": "Alice",
            "tags": [[["ring"], [40, 44]], [["red"], [31, 34]]],
        }
        dt = DataTree.from_records([records])

        dt2 = dt.expr(
            assign(
                b.flat_tags,
                chain(
                    flatten(b.tags, level=-1),
                    ops_filter(_, lambda x: isinstance(x, str)),
                ),
            ),
        )

        # flat_tags should be ['ring', 'red'] for Alice
        first, = list(dt2.scan())
        self.assertEqual(first[0].data["flat_tags"], ["ring", "red"])
        # Round-trip
        self.assertEqual(dt2.invert_all().twigs, dt.twigs)


class TestSpecForkExample(unittest.TestCase):
    """Spec fork example: age-tier assignment via fork."""

    def test_fork_age_tier(self):
        records = [
            {"name": "Alice", "age": 105, "members": {}},
            {"name": "Bob",   "age": 50,  "members": {}},
            {"name": "Carol", "age": 10,  "members": {}},
        ]
        dt = DataTree.from_records(records)

        dt2 = dt.expr(fork(
            b.age > 99,
            assign(b.members.age_tier, "old"),
            assign(b.members.age_tier, "young"),
        ))

        tiers = {r.data["name"]: r.data["members"]["age_tier"]
                 for r, _ in dt2.scan()}
        self.assertEqual(tiers["Alice"], "old")
        self.assertEqual(tiers["Bob"], "young")
        self.assertEqual(tiers["Carol"], "young")
        # Round-trip
        self.assertEqual(dt2.invert_all().twigs, dt.twigs)


class TestM0Evaluator(unittest.TestCase):
    """M0 evaluator tests: OPS, _ outside chain raises, missing field fails."""

    def test_basic_arithmetic(self):
        from sunbear.Record import Record
        from sunbear.expr.eval import eval_value
        from sunbear.expr.ast import Col, Lit, BinOp

        r = Record({"age": 30})
        age = Col("age")
        expr = (age - Lit(1)) * Lit(2)
        self.assertEqual(eval_value(expr, r), 58)

    def test_placeholder_raises_outside_chain(self):
        from sunbear.Record import Record
        from sunbear.expr.eval import eval_value

        r = Record({})
        with self.assertRaises(RuntimeError):
            eval_value(_, r)

    def test_missing_field_fails_fast(self):
        from sunbear.Record import Record
        from sunbear.expr.eval import eval_value
        from sunbear.expr.ast import Col, Lit

        r = Record({})
        # Arithmetic on None should raise (Python default behavior)
        with self.assertRaises(TypeError):
            eval_value(Col("missing") + Lit(1), r)


class TestNamespaceHelpers(unittest.TestCase):
    """M0 namespace tests."""

    def test_b_record_age(self):
        self.assertEqual(b.record.age.indexer, "record.age")

    def test_b_bracket_fallback(self):
        self.assertEqual(b["x y"].indexer, "x y")

    def test_as_indexer_on_symbol(self):
        col = Sym("a.b")
        self.assertEqual(as_indexer(col), "a.b")

    def test_as_indexer_on_string(self):
        self.assertEqual(as_indexer("a.b"), "a.b")

    def test_as_indexer_on_path_builder(self):
        self.assertEqual(as_indexer(b.profile.age), "profile.age")


class TestInspectAcceptsSymbols(unittest.TestCase):
    """DataTree.inspect should accept Sym/PathBuilder, not only raw indexers."""

    def setUp(self):
        self.dt = DataTree.from_records([
            {"commit": {"record": {"facets": [{"features": [{"tag": "x"}]}]}}},
            {"commit": {"record": {"facets": []}}},
        ])

    def test_inspect_with_string(self):
        s = self.dt.inspect("commit.record.facets")
        # Name resolution may differ — just check it doesn't raise and
        # the Schema or SchemaList has a sensible .name
        name = s.name if hasattr(s, "name") else s[0].name
        self.assertIn("commit.record.facets", name)

    def test_inspect_with_sym(self):
        s = self.dt.inspect(Sym("commit.record.facets"))
        name = s.name if hasattr(s, "name") else s[0].name
        self.assertIn("commit.record.facets", name)

    def test_inspect_with_pathbuilder(self):
        s = self.dt.inspect(b.commit.record.facets)
        name = s.name if hasattr(s, "name") else s[0].name
        self.assertIn("commit.record.facets", name)

    def test_inspect_three_styles_same_name(self):
        s_str = self.dt.inspect("commit.record.facets")
        s_sym = self.dt.inspect(Sym("commit.record.facets"))
        s_pb = self.dt.inspect(b.commit.record.facets)
        n_str = s_str.name if hasattr(s_str, "name") else s_str[0].name
        n_sym = s_sym.name if hasattr(s_sym, "name") else s_sym[0].name
        n_pb = s_pb.name if hasattr(s_pb, "name") else s_pb[0].name
        self.assertEqual(n_str, n_sym)
        self.assertEqual(n_str, n_pb)


class TestChainValidation(unittest.TestCase):
    """M2 chain validation tests."""

    def test_seed_must_not_contain_placeholder(self):
        with self.assertRaises(ValueError):
            chain(_, flatten(b.x, -1))

    def test_step_must_contain_placeholder(self):
        with self.assertRaises(ValueError):
            chain(flatten(b.x, -1), flatten(b.y, -1))  # step has no _


class TestInvertibility(unittest.TestCase):
    """L1/L2 invertibility for every lowering."""

    def test_assign_round_trip(self):
        dt = DataTree.from_records([{"a": 1}, {"a": 2}, {"a": 3}])
        out = dt.expr(assign(b.doubled, b.a * 2))
        self.assertEqual(out.invert_all().twigs, dt.twigs)

    def test_keep_round_trip(self):
        dt = DataTree.from_records([{"a": 1}, {"a": 2}, {"a": 3}])
        out = dt.expr(keep(b.a > 1))
        self.assertEqual(out.invert_all().twigs, dt.twigs)

    def test_assign_then_keep_round_trip(self):
        dt = DataTree.from_records([{"a": 1}, {"a": 2}, {"a": 3}])
        out = dt.expr(
            assign(b.doubled, b.a * 2),
            keep(b.doubled > 2),
        )
        self.assertEqual(out.invert_all().twigs, dt.twigs)

    def test_fork_round_trip(self):
        dt = DataTree.from_records([
            {"a": 1, "tier": None},
            {"a": 5, "tier": None},
        ])
        out = dt.expr(fork(
            b.a > 3,
            assign(b.tier, "big"),
            assign(b.tier, "small"),
        ))
        self.assertEqual(out.invert_all().twigs, dt.twigs)

    def test_case_round_trip(self):
        dt = DataTree.from_records([
            {"a": 1, "tier": None},
            {"a": 5, "tier": None},
            {"a": 10, "tier": None},
        ])
        out = dt.expr(case(
            (b.a >= 10, assign(b.tier, "huge")),
            (b.a >= 5,  assign(b.tier, "big")),
            default=[assign(b.tier, "small")],
        ))
        self.assertEqual(out.invert_all().twigs, dt.twigs)

    def test_assign_overwrite_existing_field(self):
        dt = DataTree.from_records([{"a": 1, "a_copy": 99}])
        out = dt.expr(assign(b.a_copy, b.a + 100))
        self.assertEqual(out.invert_all().twigs, dt.twigs)
        for r, _ in out.scan():
            self.assertEqual(r.data["a_copy"], 101)

    def test_assign_to_missing_nested_branch_creates_then_undoes(self):
        """The previously-biting edge case: assign into a path whose
        intermediate branch does not yet exist."""
        dt = DataTree.from_records([{"a": 1}])  # no `profile` key
        out = dt.expr(assign(b.profile.score, b.a * 10))
        # New branch was created
        for r, _ in out.scan():
            self.assertEqual(r.data["profile"]["score"], 10)
        # Undo drops the new branch cleanly
        self.assertEqual(out.invert_all().twigs, dt.twigs)


class TestFuzzProperty(unittest.TestCase):
    """Random expr-pipeline property test — regression net for round-trip bugs."""

    def test_random_pipelines(self):
        import random
        random.seed(0)
        n = 30
        records = []
        for i in range(n):
            records.append({
                "a": random.randint(0, 100),
                "b": random.choice([1, 2, 3, None]),
                "tags": [random.randint(0, 10) for _ in range(random.randint(0, 3))],
            })
        dt = DataTree.from_records(records)

        for trial in range(20):
            test_dt = DataTree.from_records(records)
            stmts = []
            # Random sequence of assigns and keeps
            for _ in range(random.randint(1, 4)):
                kind = random.choice(["assign_new", "assign_overwrite", "keep"])
                if kind == "assign_new":
                    target = random.choice([b.x, b.x2, b.x3, b.profile.score])
                    value = random.choice([b.a + b.b, b.a * 2, b.a - b.b, b.a])
                    if isinstance(value, int):
                        value = b.a
                    stmts.append(assign(target, value))
                elif kind == "assign_overwrite":
                    stmts.append(assign(b.a, b.a + 1))
                else:
                    pred = random.choice([b.a > 30, b.a < 70, b.a == b.a])
                    stmts.append(keep(pred))
            try:
                out = test_dt.expr(*stmts)
                # Each step's invert is the inverse
                back = out.invert_all()
                self.assertEqual(
                    back.twigs, test_dt.twigs,
                    f"Trial {trial}: round-trip failed for stmts {stmts}"
                )
            except (TypeError, NotImplementedError, KeyError):
                # Some random combos are valid to fail (e.g. None arithmetic)
                pass


class TestSboLength(unittest.TestCase):
    """sbo.length / size / count — value-tier length helper.

    Lets you filter by the size of a field without falling back to
    Python's `len()` (which can't be overloaded to return a Call).
    """

    def setUp(self):
        self.records = [
            {"name": "Alice", "tags": ["a", "b", "c"]},
            {"name": "Bob",   "tags": []},
            {"name": "Carol", "tags": ["x"]},
        ]
        self.dt = DataTree.from_records(self.records)

    def test_length_keep_nonzero(self):
        out = self.dt.expr(keep(sbo_length(b.tags) > 0))
        names = [r.data["name"] for r, _ in out.scan()]
        self.assertEqual(sorted(names), ["Alice", "Carol"])
        self.assertEqual(out.invert_all().twigs, self.dt.twigs)

    def test_length_size_alias(self):
        out = self.dt.expr(keep(sbo_size(b.tags) >= 1))
        self.assertEqual(len(out), 2)

    def test_length_count_alias(self):
        out = self.dt.expr(keep(sbo_count(b.tags) > 0))
        self.assertEqual(len(out), 2)

    def test_length_on_string_field(self):
        # "Bob" has length 3, others 5
        out = self.dt.expr(keep(sbo_length(b.name) > 3))
        names = [r.data["name"] for r, _ in out.scan()]
        self.assertEqual(sorted(names), ["Alice", "Carol"])

    def test_length_with_assign(self):
        # assign tag_count, then keep rows with count > 1
        out = self.dt.expr(
            assign(b.tag_count, sbo_length(b.tags)),
            keep(sbo_length(b.tags) > 1),
        )
        for r, _ in out.scan():
            self.assertEqual(r.data["tag_count"], 3)  # only Alice
        self.assertEqual(len(out), 1)

    def test_length_on_none_returns_zero(self):
        # Missing field should give 0 (via the runtime's None-guard)
        dt = DataTree.from_records([{"a": 1}, {"a": 2}])
        out = dt.expr(assign(b.missing_count, sbo_length(b.nonexistent)))
        for r, _ in out.scan():
            self.assertEqual(r.data["missing_count"], 0)
        self.assertEqual(out.invert_all().twigs, dt.twigs)


class TestExprCallable(unittest.TestCase):
    """Expr.__call__ produces a MapAssign statement.

    Lets you write:
        dt.expr(b.createdAt(lambda t: datetime.fromisoformat(t)))

    which is sugar for:
        assign(b.createdAt, sbo.map(b.createdAt, fn))
    """

    def setUp(self):
        self.dt = DataTree.from_records([
            {"name": "Alice", "age": 30},
            {"name": "Bob",   "age": 25},
            {"name": "Carol", "age": 40},
        ])

    def test_callable_overwrites_in_place(self):
        out = self.dt.expr(b.age(lambda x: x * 2))
        for r, _ in out.scan():
            expected = {"Alice": 60, "Bob": 50, "Carol": 80}[r.data["name"]]
            self.assertEqual(r.data["age"], expected)
        # Round-trip
        self.assertEqual(out.invert_all().twigs, self.dt.twigs)

    def test_callable_round_trip(self):
        out = self.dt.expr(b.age(lambda x: x + 100))
        for r, _ in out.scan():
            self.assertIn(r.data["age"], [130, 125, 140])
        self.assertEqual(out.invert_all().twigs, self.dt.twigs)

    def test_callable_with_extra_args(self):
        # Multiply by a constant captured as a kwarg
        out = self.dt.expr(b.age(lambda x, factor: x * factor, factor=3))
        for r, _ in out.scan():
            self.assertIn(r.data["age"], [90, 75, 120])

    def test_callable_combined_with_keep(self):
        out = self.dt.expr(
            b.age(lambda x: x * 10),
            keep(b.age > 200),
        )
        # All ages * 10 are > 200, so all rows pass
        self.assertEqual(len(out), 3)
        for r, _ in out.scan():
            self.assertGreater(r.data["age"], 200)
        self.assertEqual(out.invert_all().twigs, self.dt.twigs)

    def test_map_assign_with_explicit_target(self):
        # map_assign(target, source, fn) writes to a new field
        out = self.dt.expr(map_assign(b.age_doubled, b.age, lambda x: x * 2))
        for r, _ in out.scan():
            expected = {"Alice": 60, "Bob": 50, "Carol": 80}[r.data["name"]]
            self.assertEqual(r.data["age_doubled"], expected)
        # Original age preserved
        self.assertEqual(out.invert_all().twigs, self.dt.twigs)

    def test_callable_returns_mapassign_statement(self):
        from sunbear.expr.ast import MapAssign
        stmt = b.age(lambda x: x * 2)
        self.assertIsInstance(stmt, MapAssign)
        # The default target is the source
        self.assertEqual(stmt.target.indexer, stmt.source.indexer)


if __name__ == "__main__":
    unittest.main()
