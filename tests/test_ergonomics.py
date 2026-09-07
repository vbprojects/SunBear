"""Regression tests for high-impact public API correctness guards."""
import unittest

from sunbear import DataTree
from sunbear.expr import b


class TestExpressionTruthiness(unittest.TestCase):
    def test_python_and_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "Combine predicates with"):
            (b.age >= 18) and (b.active == True)

    def test_python_or_is_rejected(self):
        with self.assertRaisesRegex(TypeError, "Combine predicates with"):
            (b.age >= 18) or (b.active == True)


class TestJoinValidation(unittest.TestCase):
    def test_invalid_mode_does_not_consume_right_input(self):
        consumed = []

        def right_rows():
            consumed.append(True)
            yield {"id": 1}

        left = DataTree.from_records([{"id": 1}])
        with self.assertRaisesRegex(ValueError, "unsupported join mode"):
            left.join(right_rows(), on="id", how="outer")
        self.assertEqual(consumed, [])

    def test_left_join_retains_unmatched_rows(self):
        left = DataTree.from_records([{"id": 1}, {"id": 2}])
        result = left.join([{"id": 1, "value": "x"}], on="id", how="left")
        self.assertEqual(result.collect(), [
            {"id": 1, "value": "x"},
            {"id": 2},
        ])


if __name__ == "__main__":
    unittest.main()
