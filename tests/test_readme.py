"""Keep the README quick-start result synchronized with public behavior."""
import unittest

import sunbear as sb
from sunbear.expr import assign, b, keep, sbo


class TestReadmeQuickStart(unittest.TestCase):
    def test_expression_pipeline(self):
        records = [
            {"name": "Alice", "age": 30, "tags": [["ring"], ["gold"]]},
            {"name": "Bob", "age": 25, "tags": []},
            {"name": "Carol", "age": 17, "tags": [["silver"], ["bronze"]]},
        ]

        result = sb.DataTree.from_records(records).expr(
            assign(b.status, "active"),
            assign(b.flat_tags, sbo.flatten(b.tags, -1)),
            keep(b.age >= 18),
        ).collect()

        self.assertEqual(result, [
            {
                "name": "Alice", "age": 30,
                "tags": [["ring"], ["gold"]],
                "status": "active", "flat_tags": ["ring", "gold"],
            },
            {
                "name": "Bob", "age": 25, "tags": [],
                "status": "active", "flat_tags": [],
            },
        ])


if __name__ == "__main__":
    unittest.main()
