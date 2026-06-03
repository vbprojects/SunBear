import unittest
from sunbear.DataTree import DataTree
from sunbear.DataBranch import DataBranch
from sunbear.utils import col, resolve_path
import notates  # to load select method

class TestExpressionBuilderAssignSelect(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"post": {"uri": "uri1", "record": {"text": "hello", "author": "a1", "stats": {"likes": 5}}}},
            {"post": {"uri": "uri2", "record": {"text": "world", "author": "a2", "stats": {"likes": 10}}}},
        ]
        self.dt = DataTree(self.records)

    def test_assign_string_path(self):
        # We assign a new field 'new_text' equal to a literal string
        dt2 = self.dt[:, "new_text"].assign('my_literal_str').collect().mat
        
        recs = dt2.records
        self.assertEqual(len(recs), 2)
        self.assertEqual(recs[0]["new_text"], "my_literal_str")
        self.assertEqual(recs[1]["new_text"], "my_literal_str")
        self.assertEqual(recs[0]["post"]["uri"], "uri1") # Check standard fields are intact

    def test_assign_expression(self):
        # We assign a new field 'likes_copy' equal to an expression evaluated on 'post.record.stats.likes'
        class LikesPlusOne:
            def evaluate(self, record):
                return resolve_path(record, ['post', 'record', 'stats', 'likes']) + 1

        dt2 = self.dt[:, "likes_plus_one"].assign(LikesPlusOne()).collect().mat
        
        recs = dt2.records
        self.assertEqual(recs[0]["likes_plus_one"], 6)
        self.assertEqual(recs[1]["likes_plus_one"], 11)

    def test_assign_kwargs(self):
        # Assign multiple paths at once using kwargs and db.col if needed.
        dt2 = self.dt.assign(new_uri=col('post.uri'), author_copy=col('post.record.author')).collect().mat
        recs = dt2.records
        
        self.assertEqual(recs[0]["new_uri"], "uri1")
        self.assertEqual(recs[0]["author_copy"], "a1")

    def test_select_macro(self):
        # Test the refactored select method using pipeline approach
        dt2 = self.dt.select(
            my_uri="post.uri",
            my_text=col("post.record.text")
        ).collect().mat
        
        recs = dt2.records
        self.assertEqual(len(recs), 2)
        # Verify it successfully projected out only the selected columns with their new names
        self.assertIn("my_uri", recs[0])
        self.assertIn("my_text", recs[0])
        self.assertNotIn("post", recs[0]) # Should be filtered out by `.path()`
        
        self.assertEqual(recs[0]["my_uri"], "uri1")
        self.assertEqual(recs[0]["my_text"], "hello")

if __name__ == '__main__':
    unittest.main()
