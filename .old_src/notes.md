# SunBear Data Engine Specification

SunBear implements DataTree's, a lightweight graph database specifically meant for parsing large amounts of JSON records. It is designed to use lazy execution.

Syntax includes a mix of pandas and R dataframe syntax.

## 1. Schemas

DataTrees track Schemas, which are named tuples representing the structure of records. Schemas are themselves trees where the nodes are names and the leaves are types. Schema types can be Unions, Lists, or Primitives. Custom types can be defined with membership functions.

The purpose of Schemas is to filter out records in mixed environments, make traversal easier, and provide a way to interpret and extract information from REST/JSON-RPC/JSON.

Schemas are named tuples with specific equivalence:

```python
(a = (b = int, c = str)) == (a = (b = str, c = int)) # True

```

Schemas are type invariant for leaves. However, we store the schema that can represent the maximum amount of records, so in this case the schema would be:

```python
(a = (b = Union[int, str], c = Union[int, str]))

```

Schemas are also Null invariant, so if we have a record with a null value or **missing field**, we would consider them to be equivalent:

```python
(a = (b = int, c = str)) == (a = (b = int)) == (a = (b = int, c = None)) # True

```

Schemas are not invariant to named fields, so the following would not be equivalent:

```python
(a = (b = int, c = str)) == (a = (c = str, b = int, d = int)) # False

```

One immediate consequence is that Schemas are not transitive. $A = B$ and $B = C$ does not imply $A = C$. When multiple schemas break equivalence, a warning is raised and we move to reconcile.

Reconciliation can be done by removing or adding branches; the goal is to find the minimum tree that re-establishes transitivity in the current set of schemas.

While in a non-reconciled state, records can be part of multiple schemas. The process of reconciliation will remap records to a single schema.

Operations on schemas themselves are lazy, operations to schemas effect all members. For example, if we have a schema A with 1000 records, and we do A = A + (d = int), we are not going to immediately add the field d to all 1000 records, instead we will just update the schema. When we access a record, we will check the schema for that record and apply the necessary transformations on the fly.

### Inferred vs. Projection Schemas (Design Principle)

To resolve the conflict between mutating a schema and preserving the mathematical bounds of the raw data, SunBear distinguishes between:

* **Inferred Schemas:** The read-only structural truth of the data in memory.
* **Projection Schemas:** A localized cast or view applied to a DataBranch. When a user executes A = A + (d = int), the underlying inferred schema is untouched. The engine generates a Projection Schema on the resulting DataBranch that dynamically injects d = None (or a default value) at materialization.

## 2. Paths

Paths apply to all three structures. A path is a collection of named nodes that represent a location in the tree, can be represented as any ordered collection of strings, for example, ["a", "b", "c"], "abc".split(''), ("a", "b", "c").

### Path Ambiguity Resolution (Design Principle)

To prevent parser ambiguity between vertical depth traversal and horizontal field projection during multidimensional indexing, SunBear enforces strict type signatures for paths:

* **Depth Traversal:** Exclusively utilizes tuple structures (e.g., ("education", "degree")) or dot-notation strings ("education.degree").
* **Breadth Projection:** Exclusively utilizes list structures (e.g., ["name", "age"]).

## 3. Operations on Schemas

We have a few operations we can perform on schemas; delete, add, move:

* **Delete** takes a path, a sequence of named nodes, a type, and removes the type from the leaf. We may also remove the node itself.
* **Add** takes a path, a sequence of named nodes, a type, and adds the type to the leaf. We may only add a type, we cannot add an empty node.
* **Move** takes a source path, a destination path, and moves the type from the source to the destination. We can only move nodes, we cannot move types.

## 4. Underlying Data Structure

Schemas themselves are trees of nodes. Nodes either are a leaf, which is a type, or a branch, which is a collection of other nodes.

Types can be primitives, unions, lists, or membership functions. Primitives are basic data types like int, str, float, etc. Unions are a collection of types that can represent a value. Lists are a collection of types that can represent a list of values. Membership functions are custom functions that can be used to define custom types.

If we encounter a list of records in traversal, the type becomes a DataTree itself. When we encounter a Sub DataTree, we may also query it from the parent tree, for example if we have a record with a field a that is a list of records with fields b and c, we can query for a.b and a.c from the parent tree. This will return a list for each record with the corresponding field instead of a single value for each record.

## 5. DataTrees

DataTrees are a collection of records. A record is any valid Python dictionary where keys are strings. Values can be any valid Python object.

The DataTree stores a map of integers to schemas. It also stores a collection of records and tracks each record's membership to schemas. When we first load a list of records, we can if we do not defer evaluation, iterate through all records, identify all schemas, and assign a set of integers representing the schemas to each record. This allows us to quickly query for records that match a specific schema, and also allows us to quickly update the schemas when we perform operations on them. This is its own function called build_schemas. If we defer evaluation then we can build schemas on the fly.

Schemas are built iteratively as we encounter new records. When we encounter a new record, we check if it matches any existing schema. If it does, we assign the corresponding integer to the record. If the record is more specific than any existing schema, we may update the schema. If it does not, we create a new schema for that record and assign a new integer to the record. This is also where we check for equivalence and raise warnings if necessary. We store a variable _reconciled that indicates if we are in a reconciled state or not. If we are not in a reconciled state, we can have multiple schemas that are not equivalent, and records that belong to multiple schemas. When we perform reconciliation, we find the minimum tree that can represent all the schemas and remap records to the new schema.

Internally a DataTree stores a private variable stale, which is a boolean indicating if the tree needs to evaluate lazy operations. Some operations will automatically trigger evaluation. For example, loading a list of records will trigger evaluation, querying the length of the tree will trigger evaluation, etc.

### Lazy Operations

Adding and removing records will trigger evaluation. On evaluation we rebuild all schemas and attempt to keep mappings consistent. If we cannot keep mappings consistent, we raise a warning and move to reconcile.

If we change a schema, we do not need to trigger evaluation. Lazy operations like filtering, selecting, mapping, etc. do not trigger evaluation. Even summary operations like head can be computed dynamically.

Adding records does not trigger evaluation, it does trigger a check for schema membership, but it does not trigger a rebuild of schemas.

Deleting records does trigger evaluation, because we need to check if any schemas are now empty and remove them if necessary. In most cases we should prefer to use filtering to remove records, as it does not trigger evaluation.

### Deletion and Tombstoning (Design Principle)

To mitigate the $O(N)$ penalty of eager evaluation on record deletion, SunBear implements **Deferred Garbage Collection via Tombstoning**. When records are deleted, the system marks the record index within a sparse boolean mask (a tombstone) and flags stale = True. Schemas are permitted to hold a theoretical count == 0 during the non-evaluated state. Only upon materialization (e.g., .length(), .build_schemas()) does the garbage collector physically purge tombstoned records and prune orphaned schemas.

Lazy operations will return a DataBranch, which is a view of the DataTree with the lazy operations applied. When we access a record from a DataBranch, we will check if it matches the lazy operations and return the corresponding value.

Operations can be shallow, deep, chained, etc. Syntax should include a mix of pandas and R dataframe syntax.

## 6. Traversal

We use multidimensional indexing for traversal. The first dimension is the schema, the second dimension is the path.

```python
records = [
    {"name": "Alice", "age": 30, "city": "New York"},
    {"name": "Bob", "age": 25, "city": "Los Angeles"},
    {"name": "Charlie", "age": 35, "city": "Chicago"},
    {"name" : "David", "occupation": "Engineer"}
]
dt = DataTree(records)
dt[0, "age"] # returns DataBranch, lazy operation returning [30, 25, 35]
dt[1, "occupation"] # returns DataBranch, lazy operation returning ["Engineer"]
dt[[1, 0], "name"] # returns DataBranch, lazy operation returning ["Alice", "Bob", "Charlie", "David"]
dt[:, "city"] # returns DataBranch, lazy operation returning ["New York", "Los Angeles", "Chicago", None]
dt[:, ["name", "age", "occupation"]] # returns DataBranch, lazy operation returning [["New York", 30, None], ["Los Angeles", 25, None], ["Chicago", 35, None], ["David", None, "Engineer"]]

```

Deeper paths can be accessed by passing structural representations:

```python
records = [
    {"name": "Alice", "age": 30, "city": "New York", "education": {"degree": "Bachelor's", "major": "Computer Science"}},
    {"name": "Bob", "age": 25, "city": "Los Angeles", "education": {"degree": "Master's", "major": "Data Science"}},
    {"name": "Charlie", "age": 35, "city": "Chicago", "education": {"degree": "PhD", "major": "Physics"}},
    {"name" : "David", "occupation": "Engineer"}
]

# Using tuples to eliminate parser ambiguity for depth traversal
dt[0, [[("education", "degree"), "name"]]] 
# returns DataBranch, lazy operation returning [["Bachelor's", "Alice"], ["Master's", "Bob"], ["PhD", "Charlie"]]

```

Sub DataTrees can also be accessed in this way:

```python
records = [
    {"name" : "Alice", "companies" : [{"name": "Google", "position": "Software Engineer"}, {"name": "Facebook", "position": "Data Scientist"}]},
    {"name" : "Bob", "companies" : [{"name": "Amazon", "position": "Data Engineer"}]},
    {"name" : "Charlie", "companies" : [{"name": "Microsoft", "position": "Product Manager"}, {"name": "Apple", "position": "Designer"}]},
    {"name" : "David", "occupation": "Engineer"}
]

dt[0, [[("companies", "name"), "name"]]] 
# returns DataBranch, lazy operation returning [[["Google", "Facebook"], "Alice"], [["Amazon"], "Bob"], [["Microsoft", "Apple"], "Charlie"]]

```

```{python}

dt[{"name" : Any, "age" : Any}, :].collect() # Iterates through records but only loads name and age

dt[:, ["name", "age"]].collect() # Loads the entire record structure then extracts name and age, not space efficient and requires keeping in memory the entire record.

```

The difference here is that the first operation will not load the entire record structure, instead it enforces a schema and only loads those fields. While both operations will return similar results, the first one nessicary for streaming large amounts of data for which we are only interested in a subset of the fields.

### Tensor Alignment and Exploding (Design Principle)

Because returning nested lists of varying lengths ([[["Google", "Facebook"], "Alice"], ...]) prevents zero-copy handoffs to downstream vectorized libraries (like NumPy or Arrow), SunBear implements .explode(). This operation flattens nested DataBranches along the inner array axis, duplicating scalar fields to match the cardinality of the expanded lists, thereby generating a uniform, 2D continuous array.

We may also specify a schema as the first dimension. For example, if we would like all records that have a certain path. Remember, schemas are null invariant.

```python
records = [
    {"name": "Alice", "age": 30, "city": "New York"},
    {"name": "Bob", "age": 25, "city": "Los Angeles"},
    {"name": "Charlie", "age": 35, "city": "Chicago"},
    {"name" : "David", "occupation": "Engineer"}
]

dt[{"age" : int}, "city"] 
# returns DataBranch, lazy operation returning ["New York", "Los Angeles", "Chicago"]

```

Additional filtering can be done by chaining operations. All of the below are valid operations:

```python
dt.not(isna)[:, "age"].shallow(lambda x: x > 30) # isna is both a function and a method
dt.isna().length()
len(dt.isna())
dt.deep(isna).assign(1)
dt[:, "age"].not(lambda x: x > 30)

```

## 7. Merges and Joins

Merges, Joins, and other operations that combine multiple trees will trigger evaluation. Merges and Joins require specifying a map from two schemas to one.

Indexing can be done dynamically, indices do not need to be integers and do not need to be unique, but must be sortable. Merges and Joins are performed on the same index, so if we have two trees with different indices, we need to specify how to map the indices to each other. We must also specify how to map the schemas to each other. If an indice is duplicated, we will perform a cartesian product on the records with the same indice.

We can specify custom functions that take 2 schemas and specify how to merge them. For convenience, we may do so by using move, adds, and deletes. For example, we may choose to move all root fields from one schema to another. We may choose to take the Union, Intersection, differences, etc.

## 8. Data Branches

Data Branches are views of DataTrees. They are a collection of lazy operations on a DataTree, represented internally as a Directed Acyclic Graph (DAG) of transformations.

A DataBranch does not hold physical data. Instead, it holds:

1. **A Pointer** to the parent DataTree or upstream DataBranch.
2. **An Operation Node** containing the callable transformation (e.g., filter, map, assign).
3. **A Projection Schema** defining the structural output expected once the operations are evaluated.

When materialization is triggered (via terminal methods like .collect(), or iterating over the branch), the engine compiles the DAG and executes the sequence of operations against the physical records in the base DataTree in a single pass, applying bounds checking via the active Projection Schema.

Data Branches can be turned into DataTrees by calling .collect(), which will trigger evaluation and return a new DataTree with the resulting records. 

# Aggregations and Partitions

One advantage of the tree based structure is that we can naturally define common operations as transformations from one structure to another, and these transformations can be lazy and composable with the rest of the api. For example, a groupby operation in pandas will if collected return a list of tuples where the first element is the group and the second element is a DataFrame. The issue here is that this operation has not turned a dataframe into a dataframe due to the tabular structure. 

SunBear can similarly partition DataTrees by a value of a node, but also ensure that the transformation is from a DataTree to a DataTree. Take the following example:

dt[:, "occupation"].group_by()[:, "members.city"].group_by().collect()

```python
records = [
    {"name": "Alice", "age": 30, "city": "New York", "occupation": "Engineer"},
    {"name": "Bob", "age": 25, "city": "Los Angeles", "occupation": "Engineer"},
    {"name": "Charlie", "age": 35, "city": "Chicago", "occupation": "Manager"},
    {"name" : "David", "age": 40, "city": "New York", "occupation": "Manager"}
]
dt = DataTree(records)
dt[:, "occupation"].group_by().collect()
# final_structure
[
    {
        "occupation" : "Engineer",
        "members" : [
            {"name": "Alice", "age": 30, "city": "New York", "occupation": "Engineer"},
            {"name": "Bob", "age": 25, "city": "Los Angeles", "occupation": "Engineer"}
        ]
    },
    {
        "occupation" : "Manager",
        "members" : [
            {"name": "Charlie", "age": 35, "city": "Chicago", "occupation": "Manager"},
            {"name" : "David", "age": 40, "city": "New York", "occupation": "Manager"}
        ]
    }
]

dt[:, "city"].group_by()[:, "members.occupation"].group_by().collect()
# final_structure
[{
    "city" : "New York",
    "members" : [
        {
            "occupation" : "Engineer",
            "members" : [
                {"name": "Alice", "age": 30, "city": "New York", "occupation": "Engineer"}
            ]
        },
        {
            "occupation" : "Manager",
            "members" : [
                {"name" : "David", "age": 40, "city": "New York", "occupation": "Manager"}
            ]
        }
    ]
},
{
    "city" : "Los Angeles",
    "members" : [
        {
            "occupation" : "Engineer",
            "members" : [
                {"name": "Bob", "age": 25, "city": "Los Angeles", "occupation": "Engineer"}
            ]
        }
    ]
},
{
    "city" : "Chicago",
    "members" : [
        {
            "occupation" : "Manager",
            "members" : [
                {"name": "Charlie", "age": 35, "city": "Chicago", "occupation": "Manager"}
            ]
        }
    ]
}
]
```
Here we are taking records with the same schema and maintaining them as such, we may at times want to break this by dynamically creating a node from the data itself. This will break schema and sometimes lead to non-transitive schemas, but purely for flexibility we allow this. 

```python

db = dt[:, "occupation"].filter(lambda x: x == "Engineer")
db.add_path("..", db[:, "occupation"]) # Add a path before the root with the value Engineer (mutates parent tree)
dt.collect()
[
    {"Engineer" : {"name": "Alice", "age": 30, "city": "New York", "occupation": "Engineer"}},
    {"Engineer" : {"name": "Bob", "age": 25, "city": "Los Angeles", "occupation": "Engineer"}},
    {"name": "Charlie", "age": 35, "city": "Chicago", "occupation": "Manager"},
    {"name" : "David", "age": 40, "city": "New York", "occupation": "Manager"}
]

```
Now we move to another level of complexity, aggregating records into a single record by making a new datatree and appending it as a path. Because `dt[:, "Engineer"]` queries all records across the tree, records missing the "Engineer" field evaluate to `None` and are skipped during aggregation, while those containing the "Engineer" field are grouped together.

```python
dt[:, "Engineer"].aggregate().collect()
[
    {"Engineer" : [
        {"name": "Alice", "age": 30, "city": "New York", "occupation": "Engineer"},
        {"name": "Bob", "age": 25, "city": "Los Angeles", "occupation": "Engineer"}
    ]},
    {"name": "Charlie", "age": 35, "city": "Chicago", "occupation": "Manager"},
    {"name" : "David", "age": 40, "city": "New York", "occupation": "Manager"}
]

```
Thus groupby is just a combination of filters, path additions, and aggregation. And these operations can be chained to achieve more complex results.