DataTree primarily row based instead of pandas columnar format.

We have classes of operations which are garunteed to have some other function when composed form an identity.

Inother words, for all operations that create a valid DataTree state, there exists an inverse operation within the set of operations that can be applied to the resulting DataTree to return it to the original state.

# Primary Data Structure: Record

A record consists of data and metadata. All records in a DataTree have a uniquely associated metadata. We may index the data by its metadata, and we may also index the metadata by the data.

An index is generally a column of the metadata. Two records may have the same index but may not have identical metadata.

# Row Map

A row wise map takes a single record and produces a single record for all records in the DataTree. We perform this with a yield, a pre operation, and a post operation but these are strictly for reducing code duplication.

The procedure is as follows:

For all records in the DataTree:
    1. Apply the pre operation on the record data and metadata, produce the pre operated record.
    2. Apply the post operation on the pre operated record data and metadata, produce the post operated record.
    3. Yield the post operated record data and metadata.

A row wise map is its own inverse. There exists another row wise map that can be applied to the resulting DataTree to return it to the original state.

# Filter and Insertion

A Filter takes a single record and produces the same record or does not produce a record for all records in the DataTree.

An Insertion simply inserts records into the end of the DataTree. An Insertion combined with a Row Map can invert a Filter. A Filter can invert an Insertion.


# One to Many and Many to One, Many to Many

This is where we start to see more complex operations. A many to one takes more than one record and produces a single record. A one to many takes a single record and produces more than one record. A many to many takes more than one record and produces more than one record.

A many to one can be inverted by a one to many. A one to many can be inverted by a many to one. A many to many can be inverted by another many to many.

A filter may invert a one to many, an insertion and a row map may invert a many to one, and a combination of filters, insertions, and row maps may invert a many to many, but these are not guaranteed.

A Reduction and Group By are examples of many to one. An explode is an example of one to many. A join is an example of many to many.

The main issue with these operations is optimizing iteration.


# Pure Interface & Backend

There needs to be some seperation of concerns, the backend needs to be threadsafe reiterable iterator.




