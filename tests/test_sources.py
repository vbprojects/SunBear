import itertools
import unittest

from sunbear import DataTree, Record, SchemaSample
from sunbear.expr import b, assign, keep


class TestSources(unittest.TestCase):
    def test_replayable_transformations(self):
        source = DataTree.from_records([{"x": 1}, {"x": 2}])
        tree = source.expr(assign(b.y, b.x + 1), keep(b.x > 1)).head(1)
        self.assertTrue(tree.replayable)
        self.assertEqual(tree.collect(), [{"x": 2, "y": 3}])
        self.assertEqual(tree.collect(), [{"x": 2, "y": 3}])

    def test_factory_is_lazy_and_reexecuted(self):
        calls = []
        def factory():
            calls.append(1)
            return [{"x": 1}]
        tree = DataTree.from_iter_factory(factory).map(lambda r: r)
        self.assertEqual(calls, [])
        self.assertIn("replayable", repr(tree))
        tree.collect()
        tree.collect()
        self.assertEqual(calls, [1, 1])

    def test_preview_retains_rows_and_is_isolated(self):
        reads = []
        def rows():
            for n in [1, 1, 2, 3]:
                reads.append(n)
                yield {"x": [n]}
        tree = DataTree.from_iter(rows())
        first = tree.peek(2)
        first[0]["x"].append(99)
        self.assertEqual(tree.peek(2), [{"x": [1]}, {"x": [1]}])
        self.assertEqual(reads, [1, 1])
        cursor = tree.iter_rows()
        self.assertEqual(next(cursor), {"x": [1]})
        self.assertEqual(tree.peek(2), [{"x": [1]}, {"x": [2]}])
        self.assertEqual(list(cursor), [{"x": [1]}, {"x": [2]}, {"x": [3]}])
        self.assertEqual(tree.collect(), [])
        self.assertFalse(tree.replayable)

    def test_infinite_source_bounded_schema(self):
        reads = []
        def rows():
            for n in itertools.count():
                reads.append(n)
                yield {"x": n}
        tree = DataTree.from_iter(rows())
        sample = tree.infer_schema(sample=5)
        self.assertIsInstance(sample, SchemaSample)
        self.assertEqual((sample.sampled_rows, sample.sample_limit), (5, 5))
        self.assertIs(tree.schema, sample.schema)
        self.assertEqual(reads, list(range(5)))
        self.assertEqual(tree.head(5).collect(), [{"x": n} for n in range(5)])
        self.assertEqual(reads, list(range(5)))

    def test_unknown_introspection_never_reads(self):
        reads = []
        def rows():
            reads.append(1)
            yield {"x": 1}
        tree = DataTree.from_iter(rows())
        self.assertIn("single-pass", repr(tree))
        with self.assertRaises(TypeError):
            len(tree)
        with self.assertRaises(TypeError):
            bool(tree)
        with self.assertRaises(RuntimeError):
            _ = tree.schema
        self.assertEqual(reads, [])

    def test_snapshot_remaining_and_isolated(self):
        tree = DataTree.from_iter([{"x": [1]}, {"x": [2]}])
        next(tree.iter_rows())
        snapshot = tree.materialize()
        self.assertTrue(snapshot.replayable)
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(snapshot.collect(), [{"x": [2]}])
        self.assertEqual(snapshot.collect(), [{"x": [2]}])
        self.assertEqual(tree.collect(), [])
        source = DataTree.from_records([{"x": [1]}])
        snapshot = source.materialize()
        snapshot.collect()[0]["x"].append(2)
        self.assertEqual(source.collect(), [{"x": [1]}])

    def test_combined_capability(self):
        left = DataTree.from_records([{"x": 1}])
        both = left + DataTree.from_records([{"x": 2}])
        self.assertTrue(both.replayable)
        self.assertEqual(both.collect(), both.collect())
        mixed = left + DataTree.from_iter([{"x": 2}])
        self.assertFalse(mixed.replayable)
        self.assertEqual(len(mixed.collect()), 2)
        self.assertEqual(mixed.collect(), [])

    def test_explode_replays(self):
        tree = DataTree.from_records([{"x": [1, 2]}]).explode("x")
        self.assertEqual(tree.collect(), tree.collect())

    def test_inspect_does_not_discard_sample(self):
        tree = DataTree.from_iter([{"x": 1}, {"x": 2}])
        tree.inspect("x", sample=1)
        self.assertEqual(tree.collect(), [{"x": 1}, {"x": 2}])

    def test_invalid_and_empty_samples(self):
        tree = DataTree.from_iter(itertools.repeat({"x": 1}))
        for n in [-1, True, 1.5]:
            with self.assertRaises(ValueError):
                tree.peek(n)
        self.assertEqual(tree.peek(0), [])
        self.assertEqual(DataTree.from_records([]).infer_schema().sampled_rows, 0)
