import unittest
import warnings
from typing import Callable
from src.Schema import (
    Path,
    PrimitiveType,
    NullType,
    UnionType,
    ListType,
    FunctionType,
    ThunkFunctionType,
    Leaf,
    Branch,
    infer_schema
)
from src.DataTree import DataTree
from src.DataBranch import DataBranch

class TestPathResolution(unittest.TestCase):
    def test_parse_depth(self):
        self.assertEqual(Path.parse_depth("a.b.c"), ("a", "b", "c"))
        self.assertEqual(Path.parse_depth(("d", "e")), ("d", "e"))
        with self.assertRaises(TypeError):
            Path.parse_depth(["a", "b"])

    def test_parse_breadth(self):
        self.assertEqual(Path.parse_breadth(["x", "y"]), ["x", "y"])
        with self.assertRaises(TypeError):
            Path.parse_breadth("x.y")

class TestSchemaTypes(unittest.TestCase):
    def test_primitive_equality(self):
        self.assertEqual(PrimitiveType(int), PrimitiveType(int))
        self.assertNotEqual(PrimitiveType(int), PrimitiveType(str))

    def test_null_equality(self): 
        self.assertEqual(NullType(), NullType())
        self.assertNotEqual(NullType(), PrimitiveType(int))

    def test_union_flattening(self):
        u1 = UnionType({PrimitiveType(int), PrimitiveType(str)})
        u2 = UnionType({PrimitiveType(str), PrimitiveType(int)})
        self.assertEqual(u1, u2)

    def test_thunk_function(self):
        func_a = lambda x: True
        func_b = lambda x: False
        thunk = ThunkFunctionType(func_a, func_b, 'or')
        self.assertTrue(thunk.func(None) == True) # True or False -> True

class TestSchemaInferenceAndBranch(unittest.TestCase):
    def test_infer_simple_dict(self):
        record = {"a": 1, "b": "str", "c": None}
        schema = infer_schema(record)
        self.assertIsInstance(schema, Branch)
        self.assertEqual(schema.fields["a"].type, PrimitiveType(int))
        self.assertEqual(schema.fields["b"].type, PrimitiveType(str))
        self.assertEqual(schema.fields["c"].type, NullType())

    def test_branch_subset_equivalence(self):
        record1 = {"a": 1, "b": 2}
        record2 = {"a": 1}
        
        s1 = infer_schema(record1)
        s2 = infer_schema(record2)
        
        # They should be equivalent under subset logic (missing fields -> Null invariant theoretically)
        self.assertTrue(s1 == s2)
        
        record3 = {"a": 1, "c": 3}
        s3 = infer_schema(record3)
        # s1 and s3 are not subsets of each other. 
        # (Though DataTree logic allows reconciling disjoint sets later)
        self.assertFalse(s1 == s3)

    def test_branch_reconciliation(self):
        s1 = infer_schema({"a": 1, "b": 2})
        s2 = infer_schema({"a": 1})
        reconciled = s1.reconcile(s2)
        
        self.assertIn("b", reconciled.fields)
        # s2 is missing 'b', so reconciliation makes b Union[int, Null]
        b_type = reconciled.fields["b"].type
        self.assertIsInstance(b_type, UnionType)

class TestSchemaMutations(unittest.TestCase):
    def test_add_delete_move(self):
        s1 = infer_schema({"a": {"b": 1, "c": "text"}})
        
        # Test add
        s2 = s1.add("a.d", PrimitiveType(float))
        self.assertNotIn("d", s1.fields["a"].fields) # Immutable check
        self.assertIn("d", s2.fields["a"].fields)
        self.assertEqual(s2.fields["a"].fields["d"].type, PrimitiveType(float))

        # Test delete
        s3 = s2.delete("a.b")
        self.assertNotIn("b", s3.fields["a"].fields)
        
        # Test move
        s4 = s3.move("a.c", "a.z")
        self.assertNotIn("c", s4.fields["a"].fields)
        self.assertIn("z", s4.fields["a"].fields)
        self.assertEqual(s4.fields["a"].fields["z"].type, PrimitiveType(str))

class TestDataTreeOperations(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"name": "Alice", "age": 30, "city": "New York", "education": {"degree": "Bachelor's"}},
            {"name": "Bob", "age": 25, "city": "Los Angeles", "education": {"degree": "Master's"}},
            {"name": "Charlie", "age": 35, "city": "Chicago", "education": {"degree": "PhD"}},
            {"name": "David", "occupation": "Engineer"}
        ]

    def test_initialization_and_warnings(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            dt = DataTree(self.records)
            
            # Explicitly disjoint distinct records should not raise transitivity warnings.
            self.assertEqual(len(w), 0)
            self.assertTrue(dt._reconciled)

    def test_transitivity_warning(self):
        # A=B, B=C, A!=C -> transitivity broken
        # A: a=1, b=2
        # B: b=2
        # C: b=2, c=3
        # Since B is subset of A, and B is subset of C, A==B and B==C.
        # But A and C are disjoint on 'a' and 'c' so A!=C.
        records = [
            {"a": 1, "b": 2},
            {"b": 2, "c": 3},
            {"b": 2} # This matches both A and C
        ]
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            dt = DataTree(records)
            self.assertEqual(len(w), 1)
            self.assertFalse(dt._reconciled)

    def test_depth_traversal(self):
        dt = DataTree(self.records)
        br = dt[:, "education.degree"]
        results = br.collect()
        self.assertEqual(results, ["Bachelor's", "Master's", "PhD", None])

    def test_breadth_traversal(self):
        dt = DataTree(self.records)
        br = dt[0:2, ["name", "age"]]
        results = br.collect()
        self.assertEqual(results, [["Alice", 30], ["Bob", 25]])

    def test_garbage_collection_tombstone(self):
        dt = DataTree(self.records)
        self.assertEqual(len(dt.records), 4) # Direct length observation works
        
        # Simulate tombstone deletion
        dt._tombstones[0] = True 
        dt.stale = True
        
        # Trigger GC
        self.assertEqual(dt.length(), 3)
        self.assertEqual(dt.records[0]["name"], "Bob")

if __name__ == '__main__':
    unittest.main()
