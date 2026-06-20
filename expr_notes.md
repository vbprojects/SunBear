Expr builder:

Syntatic sugar for building expressions in SunBear for DataTrees. This involves allowing assigning indexers to symbols and performing operations on them.

For example
```{python}
dt = sb.from_records(records)
age, height,normalized_age,normalized_height = Symbols("record.age", "record.height", "record.standardized_age", "record.standardized_height")
ages, heights = dt.pluck(age), dt.pluck(height)
mu_age, mu_height, std_age, std_height = np.mean(ages), np.mean(heights), np.std(ages), np.std(heights)
dt.expr(
    assign(normalized_age, (age - mu_age)/std_age),
    assign(normalized_height, (mu_height - mu_age)/std_height),
    filter(normalized_age < 50)
)
```

Note that aggregations across need to be computed outside expr, this is a row based data processing tool, columnar data should be dealt with using pandas/polars/numpy.

A symbol in this case is essentially a holder for an indexer

Symbols is the wrapper, for a little syntax sugar we should also be able to create a lazy namespace that can use field esque notation to construct indexers on the fly

```{python}
import sunbear as sb
import numpy as np
from sunbear.expr import LazyNamespace as b

dt = sb.from_records(records)
dt.select(age = b.record.age, height = b.record.height).
    expr(
        assign(b.s_age, (b.age - np.mean(dt.pluck(b.age))) / np.std(dt.pluck(b.age)))
    )
```

Shape operations should also be possible, we should be able to flatten, filter, reduce, and map within fields of a single record itself. All sbo transformations should be able to be implemented as DataTree operations, again, expr is just syntatic sugar. Therefore, the L1/L2 invertability should hold and the various operations should in underlying manner be executed with the DataTree operations at inference.

```{python}
records = {
    "name" : "Alice", "tags" : [[["ring"], [40, 44]], [["red"], [31, 34]]]
}
dt = sb.from_records(records)
import sunbear.ops as sbo
dt.expr(
    assign(b.flat_tags, sbo.flatten(b.tags, level = -1)) # flatten until we are left with no more sublists
    assign(b.flat_tags, sbo.filter(b.tags, lambda x: isinstance(x, str)))
)
```

sbo operations flatten and filter are applying to each record independantly, thus these can be represented as maps. 

Some more syntatic sugar, _ is a placeholder that allows for storing the result of a computation within a chain before going to the next one, 

```
dt.expr(
    assign(b.flat_tags, 
        sbo.chain(
            sbo.flatten(b.tags, level = -1), # flatten until
            sbo.filter(_, lambda x: isinstance(str))
        )
    )
)
```

non_mappable functions extended by sbo involve operations like fork, which under the hood run a groupby based off a given condition and then applies chains to each condition.

```
dt.expr(
    sbo.fork(b.age > 99,
        sbo.assign(b.members.age_tier, "old"),
        sbo.assign(b.members.age_tier, "young")
    )
)
```

Can also be multiple conditions and forks, although may need to be a special function for additional forks.

For now, expr is eager and sequential, might be possibility for implementing lazy, async, and parallelizable expr in the future.