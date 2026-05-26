import json
import itertools
from src.DataTree import DataTree
from src.DataBranch import DataBranch

@DataTree.register_method
@DataBranch.register_method
def head(db, n=5):
    import itertools
    return DataBranch(db, operation=lambda r: list(itertools.islice(r, n)))

records = [
    {"name": "Alice", "age": 30, "city": "New York", "occupation": "Engineer"},
    {"name": "Bob", "age": 25, "city": "Los Angeles", "occupation": "Engineer"},
    {"name": "Charlie", "age": 35, "city": "Chicago", "occupation": "Manager"},
    {"name" : "David", "age": 40, "city": "New York", "occupation": "Manager"}
]

dt = DataTree(records)
print("DataTree created")
