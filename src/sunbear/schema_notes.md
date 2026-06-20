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

The primary purpose of Schemas is to help bring data to a tidy state. A DataTree with a single schema allows for transitioning from tree based to columnar based format for more traditional data processing.

A large part of schemas is being able to visually show the tree structure of twigs effectively, allowing for both pretty printing in terminal based sessions and html outputs in ipython jupyter based environments. 

They should stay nested and allow for visual exploration. Syntatic sugar on top of schemas should allow for seeing the ratios of different types for schemes including None values.