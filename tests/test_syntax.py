"""Behavioral contracts for fluent pipelines, scope, and value accessors."""

import copy
import subprocess
import sys
import tempfile
import unittest
import sunbear as sb
from sunbear import f, selectors as cs
from sunbear.expr.eval import compile
from sunbear.record import Record


class SyntaxTests(unittest.TestCase):
    def value(self, expression, row=None):
        return compile(expression)(Record(row or {}))

    def test_namespace_identity_and_import_order(self):
        subprocess.run(
            [
                sys.executable,
                "-c",
                """
import sunbear as sb
from sunbear.DataTree import DataTree
from sunbear.Program import Program
from sunbear.Record import Record
from sunbear.Schema import Schema
assert sb.DataTree is DataTree
assert sb.Program is Program
assert sb.Record is Record
assert sb.Schema is Schema
assert sb.f is sb.b
from sunbear.cache import FileCache
from sunbear.Program import FileCache as OldCache
assert FileCache is OldCache
""",
            ],
            check=True,
        )

    def test_atomic_projection_and_sequential_assignment(self):
        tree = sb.DataTree.from_records([{"x": 1, "y": 2}])
        self.assertEqual(tree.select(x=f.y, y=f.x).one(), {"x": 2, "y": 1})
        self.assertEqual(tree.assign(x=f.y, y=f.x).one(), {"x": 2, "y": 2})
        self.assertEqual(tree.one(), {"x": 1, "y": 2})

    def test_field_alias_literal_key_and_positional_compatibility(self):
        tree = sb.DataTree.from_records([{"a": {"b": 1, "c": 2}, "literal.key": 3}])
        self.assertEqual(tree.select(f.a.b).one(), {"a": {"b": 1, "c": 2}})
        self.assertEqual(tree.select(f["literal.key"].as_("x.y")).one(), {"x.y": 3})

    def test_fluent_reuse_branch_composition(self):
        p = (
            sb.Program()
            .where(f.x > 0)
            .assign(y=f.x + 1)
            .when(f.x > 1)
            .then(sb.Program().assign(y=99))
            .end()
        )
        q = p.then(sb.Program().select("y"))
        self.assertEqual(
            sb.DataTree.from_records([{"x": 0}, {"x": 1}, {"x": 2}]).pipe(q).collect(),
            [{"y": 2}, {"y": 99}],
        )
        self.assertEqual(len(p._statements), 3)

    def test_where_short_circuit(self):
        boom = sb.lit(1).apply(lambda v: 1 / 0)
        self.assertEqual(
            sb.DataTree.from_records([{}]).where(False, boom).collect(), []
        )
        self.assertEqual(
            sb.DataTree.from_records([{}]).where_any(True, boom).collect(), [{}]
        )
        self.assertEqual(sb.DataTree.from_records([{}]).reject(False).collect(), [{}])

    def test_update_builder_once_and_isolation(self):
        calls = []

        def builder(v):
            calls.append(True)
            return v + 1

        source = sb.DataTree.from_records([{"a": {"b": 1}}, {"a": {"b": 2}}])
        result = source.update(f.a.b, builder)
        self.assertEqual(result.collect(), [{"a": {"b": 2}}, {"a": {"b": 3}}])
        self.assertEqual(result.collect(), [{"a": {"b": 2}}, {"a": {"b": 3}}])
        self.assertEqual(calls, [True])
        self.assertEqual(source.first(), {"a": {"b": 1}})

    def test_chain_accepts_new_expression_nodes(self):
        from sunbear.expr import sbo, _

        self.assertEqual(
            self.value(sbo.chain(f.x, _.str.strip(), _.str.upper()), {"x": " a "}), "A"
        )
        with self.assertRaises(ValueError):
            sbo.chain(_.str.strip())
        self.assertEqual(self.value(sb.when(None).then(1).otherwise(2)), 2)

    def test_lazy_fallbacks_and_conditions(self):
        boom = sb.lit(None).apply(lambda v: 1 / 0)
        for expr in (
            sb.lit(1).fill_null(boom),
            sb.lit(1).fill_missing(boom),
            sb.lit(1).coalesce(boom),
            sb.when(True).then(1).otherwise(boom),
            sb.match("a").case("a", 1).otherwise(boom),
            sb.lit([1]).list.get(0, boom),
            sb.lit({"a": 1}).obj.get("a", boom),
        ):
            with self.subTest(expr=repr(expr)):
                self.assertEqual(self.value(expr), 1)
        self.assertIs(self.value(f.x.fill_null(1)), sb.MISSING)
        self.assertIsNone(self.value(sb.lit(None).fill_missing(1)))

    def test_scoped_items_and_outer_row(self):
        it = sb.item("entry")
        expr = f.items.list.filter(it.price <= f.budget).list.map(it.price * 2)
        self.assertEqual(
            self.value(expr, {"budget": 2, "items": [{"price": 1}, {"price": 3}]}), [2]
        )

    def test_nested_items_independent_and_safe(self):
        outer, inner = sb.item("outer"), sb.item("inner")
        expr = f.groups.list.map(
            outer.values.list.map(inner + outer.offset, item=inner), item=outer
        )
        self.assertEqual(
            self.value(expr, {"groups": [{"values": [1, 2], "offset": 10}]}), [[11, 12]]
        )
        with self.assertRaises(ValueError):
            compile(inner + 1)
        with self.assertRaises(ValueError):
            compile(
                f.groups.list.map(
                    outer.values.list.map(outer + 1, item=outer), item=outer
                )
            )
        with self.assertRaises(ValueError):
            f.groups.list.map(inner + outer)

    def test_selector_algebra_and_heterogeneous_rows(self):
        selector = (cs.starts_with("a") | cs.names("b")) - cs.names("avoid")
        data = [{"a": 1, "avoid": 0, "b": 2}, {"another": 3, "c": 4}]
        self.assertEqual(
            sb.DataTree.from_records(data).select(selector).collect(),
            [{"a": 1, "b": 2}, {"another": 3}],
        )
        self.assertEqual(
            sb.DataTree.from_records(data)
            .transform_fields(selector, lambda v: v + 10)
            .first(),
            {"a": 11, "avoid": 0, "b": 12},
        )
        self.assertEqual(
            sb.DataTree.from_records(data)
            .rename_fields(cs.names("a"), str.upper)
            .first(),
            {"A": 1, "avoid": 0, "b": 2},
        )

    def test_shape_helpers_and_presence(self):
        p = (
            sb.Program()
            .copy("a", "b")
            .rename(b="c")
            .nest("a", "c", into="obj")
            .unnest("obj", prefix="v_")
            .drop("v_c")
        )
        self.assertEqual(
            p(sb.DataTree.from_records([{"a": None}])).one(), {"v_a": None}
        )
        with self.assertRaises(sb.TransformationError):
            sb.DataTree.from_records([{}]).require_fields("id").collect()
        self.assertEqual(
            sb.DataTree.from_records([{}, {"x": None}, {"x": 0}])
            .drop_nulls("x")
            .collect(),
            [{"x": 0}],
        )

    def test_missing_and_null_propagate_accessors(self):
        for accessor in (
            lambda v: v.str.lower(),
            lambda v: v.list.len(),
            lambda v: v.obj.keys(),
            lambda v: v.sqrt(),
        ):
            self.assertIs(self.value(accessor(f.x)), sb.MISSING)
            self.assertIsNone(self.value(accessor(sb.lit(None))))
        with self.assertRaises(TypeError):
            self.value(sb.lit(1).str.lower())
        with self.assertRaises(TypeError):
            self.value(sb.lit("abc").list.len())
        self.assertEqual(self.value(sb.object(a=f.x, b=None)), {"b": None})
        with self.assertRaises(ValueError):
            self.value(sb.array(f.x))

    def test_string_accessors(self):
        cases = [
            (sb.lit(" A  b ").str.normalize_whitespace(), "A b"),
            (sb.lit("ÉLAN").str.casefold(), "élan"),
            (sb.lit("a.b").str.contains("."), True),
            (sb.lit("abc").str.contains("^b", regex=True), False),
            (sb.lit("123").str.matches(r"\d+"), True),
            (sb.lit("aaa").str.replace("a", "b"), "baa"),
            (sb.lit("aaa").str.replace_all("a", "b"), "bbb"),
            (sb.lit("aaa").str.replace("a", "b", count=0, regex=True), "aaa"),
            (sb.lit("ab12").str.extract(r"(\d+)", 1), "12"),
            (sb.lit("a1b2").str.extract_all(r"\d"), ["1", "2"]),
            (sb.lit("x:y").str.partition(":"), ["x", ":", "y"]),
            (sb.lit("x\ny").str.split_lines(), ["x", "y"]),
            (sb.lit("abc").str.slice(0, 2), "ab"),
            (sb.lit("abc").str.tail(0), ""),
            (sb.lit("x").str.pad_left(3, "0"), "00x"),
            (sb.lit("7").str.zfill(3), "007"),
        ]
        for expr, want in cases:
            with self.subTest(expr=repr(expr)):
                self.assertEqual(self.value(expr), want)
        with self.assertRaises(Exception):
            sb.Program().assign(x=f.x.str.matches("["))

    def test_list_accessors(self):
        v = sb.lit([3, 1, 3])
        it = sb.item()
        cases = [
            (v.list.unique(), [3, 1]),
            (v.list.sort(), [1, 3, 3]),
            (v.list.reverse(), [3, 1, 3]),
            (v.list.sum(), 7),
            (v.list.mean(), 7 / 3),
            (v.list.get(99, 0), 0),
            (v.list.chunk(2), [[3, 1], [3]]),
            (v.list.union([4, 1]), [3, 1, 4]),
            (v.list.intersection([1]), [1]),
            (v.list.difference([3]), [1]),
            (v.list.enumerate(1), [[1, 3], [2, 1], [3, 3]]),
            (v.list.zip([9]), [[3, 9]]),
            (v.list.count_where(it > 1), 2),
            (v.list.any(it == 1), True),
            (v.list.all(it > 0), True),
            (v.list.map(lambda x: x + 1), [4, 2, 4]),
            (v.list.reduce(lambda a, b: a + b, 10), 17),
            (sb.lit([[1], [2]]).list.flatten(), [1, 2]),
            (sb.lit([{"x": 2}, {"x": 1}]).list.sort_by(it.x), [{"x": 1}, {"x": 2}]),
        ]
        for expr, want in cases:
            with self.subTest(expr=repr(expr)):
                self.assertEqual(self.value(expr), want)
        with self.assertRaises(ValueError):
            self.value(v.list.chunk(0))

    def test_objects_numeric_and_cast(self):
        self.assertEqual(
            self.value(sb.lit({"a": 1, "b": 2}).obj.omit("b").obj.merge({"c": 3})),
            {"a": 1, "c": 3},
        )
        self.assertEqual(self.value(sb.lit({"a": 1}).obj.entries()), [["a", 1]])
        with self.assertRaises(ValueError):
            self.value(sb.lit({"a": 1, "b": 2}).obj.rename(a="b"))
        cases = [
            (abs(sb.lit(-3)), 3),
            (round(sb.lit(1.234), 2), 1.23),
            (sb.lit(9).sqrt(), 3),
            (sb.lit(5) // 2, 2),
            (7 % sb.lit(3), 1),
            (2 ** sb.lit(3), 8),
            (-sb.lit(2), -2),
            (sb.lit("oops").cast(int, errors="null"), None),
            (sb.lit("3").cast(int), 3),
            (sb.lit(2).between(1, 2), True),
            (sb.lit(2).between(1, 2, closed="none"), False),
            (sb.lit("x").replace({"x": "y"}), "y"),
        ]
        for expr, want in cases:
            self.assertEqual(self.value(expr), want)

    def test_cache_identity_for_sugar_and_callbacks(self):
        with tempfile.TemporaryDirectory() as d:
            cache = sb.cache.FileCache("syntax", directory=d)
            a = sb.Program(cache=cache).assign(n=f.x.str.len())
            b = sb.Program(cache=cache).expr(sb.ops.assign(n=f.x.str.len()))
            self.assertEqual(a._program_key(), b._program_key())
            self.assertEqual(
                a(sb.DataTree.from_records([{"x": "abc"}])).first()["n"], 3
            )
            with self.assertRaises(ValueError):
                sb.Program(cache=cache).assign(x=f.x.apply(lambda v: v))

    def test_global_conveniences_and_bounded_terminals(self):
        tree = sb.DataTree.from_records(
            [{"g": "a", "x": 2}, {"g": "a", "x": 1}, {"g": "b", "x": 3}]
        )
        self.assertEqual(
            tree.group_by(f.g).agg(n=sb.count_rows(), total=sb.sum(f.x)).collect(),
            [{"k": "a", "n": 2, "total": 3}, {"k": "b", "n": 1, "total": 3}],
        )
        self.assertEqual(tree.order_by(f.g.asc(), f.x.desc()).pluck("x"), [2, 1, 3])
        self.assertEqual(tree.top_k(2, by=f.x).pluck("x"), [3, 2])
        self.assertEqual(tree.unique_by("g").count_rows(), 2)
        self.assertEqual(tree.agg(total=sb.sum(f.x)).one(), {"total": 6})
        self.assertEqual(tree.to_columns()["x"], [2, 1, 3])
        self.assertEqual([len(batch) for batch in tree.iter_batches(2)], [2, 1])
        source = sb.DataTree.from_iter(iter([{"x": 1}, {"x": 2}, {"x": 3}]))
        self.assertFalse(source.is_empty())
        with self.assertRaises(ValueError):
            source.one()
        self.assertEqual(source.first(), {"x": 3})
        self.assertEqual(source.first("empty"), "empty")


if __name__ == "__main__":
    unittest.main()
