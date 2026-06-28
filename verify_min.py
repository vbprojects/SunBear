"""verify_min.py — smoke tests for the minimal sunbear rewrite."""
import sys
import sunbear as sb
from sunbear.expr import b, assign, keep, sbo
from sunbear.expr.sbo import chain

passed = 0
failed = 0

def check(label, ok, detail=""):
    global passed, failed
    status = "PASS" if ok else "FAIL"
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))

# ====== T1: Generator ingest ======
print("--- T1: Generator ingest ---")
def gen():
    for i in range(3):
        yield {'i': i, 'name': f'r{i}'}

dt = sb.DataTree.from_iter(gen())
collected = [r.data for r, _ in dt.scan()]
check("from_iter yields all", collected == [{'i': 0, 'name': 'r0'}, {'i': 1, 'name': 'r1'}, {'i': 2, 'name': 'r2'}])
# from_records is re-traversable (eager list)
dt2 = sb.DataTree.from_records([{'x': i} for i in range(5)])
n1 = len(dt2)
n2 = len(dt2)
check("from_records re-traversable", n1 == n2 == 5)
check("from_records single-pass safe", dt2.collect() == [{'x': 0}, {'x': 1}, {'x': 2}, {'x': 3}, {'x': 4}])


# ====== T2: Lazy filter ======
print("--- T2: Lazy filter ---")
records = [{'n': i} for i in range(10)]
dt = sb.DataTree.from_records(records)
filtered = dt.filter(lambda r, m: r.data['n'] % 2 == 0)
import itertools
sliced = list(itertools.islice(filtered.scan(), 3))
check("lazy filter slices", [r.data['n'] for r, _ in sliced] == [0, 2, 4])

# ====== T3: Schema ======
print("--- T3: Schema ---")
recs = [{'a': 1, 'b': 'hi'}, {'a': 2, 'b': 'yo'}]
dt = sb.DataTree.from_records(recs)
schema = dt.schema
check("schema is Schema", isinstance(schema, sb.Schema))
schema.show()

# ====== T4: group_by + plan cardinality ======
print("--- T4: group_by / plan ---")
recs = [{'k': 'a', 'v': 1}, {'k': 'b', 'v': 2}, {'k': 'a', 'v': 3}, {'k': 'a', 'v': 5}]
dt = sb.DataTree.from_records(recs)
plan = dt.plan('k')
exp = plan.explain()
print(f"  plan: {exp}")
check("plan builds index", len(plan.index) == 2)
check("plan order", plan.order == ['a', 'b'])
grouped = dt.group_by('k')
groups = [(r.data['k'], len(r.data['members'])) for r, _ in grouped.scan()]
check("group_by counts", groups == [('a', 3), ('b', 1)])

# ====== T5: reduce_by (single pass) ======
print("--- T5: reduce_by ---")
result = dt.reduce_by('k', lambda acc, r: acc + r.data['v'], init=0)
sums = {r.data['k']: r.data['v'] for r, _ in result.scan()}
check("reduce_by 'a'", sums.get('a') == 9)
check("reduce_by 'b'", sums.get('b') == 2)

# ====== T6: reduce (terminal) ======
print("--- T6: reduce ---")
total = dt.reduce(lambda acc, r: acc + r.data['v'], init=0)
check("reduce total", total == 11)

# empty + init
empty_dt = sb.DataTree.from_records([])
empty_total = empty_dt.reduce(lambda acc, r: acc + r.data.get('v', 0), init=0)
check("reduce empty + init", empty_total == 0)

# empty + no init must raise
try:
    empty_dt.reduce(lambda acc, r: acc + 1)
    check("reduce empty + no init raises", False)
except ValueError:
    check("reduce empty + no init raises", True)

# ====== T7: expr pipeline (assign + keep) ======
print("--- T7: expr pipeline (assign + keep) ---")
recs = [{'n': i} for i in range(5)]
dt = sb.DataTree.from_records(recs)
dt2 = dt.expr(assign(b.squared, b.n * b.n), keep(b.n > 1))
out = [r.data for r, _ in dt2.scan()]
check("expr assign+keep", out == [{'n': 2, 'squared': 4}, {'n': 3, 'squared': 9}, {'n': 4, 'squared': 16}])

# ====== T8: intra-record sbo ======
print("--- T8: intra-record sbo.filter + sbo.length ---")
recs = [{'tags': [1, 2, 3, 4, 5]}, {'tags': [10, 20, 30]}]
dt = sb.DataTree.from_records(recs)
dt2 = dt.expr(assign(b.kept, sbo.filter(b.tags, lambda x: x > 5)))
out = [r.data for r, _ in dt2.scan()]
check("sbo.filter row 0", out[0]['kept'] == [])
check("sbo.filter row 1", out[1]['kept'] == [10, 20, 30])

# ====== T9: join ======
print("--- T9: join ---")
left = [{'id': 1, 'name': 'a'}, {'id': 2, 'name': 'b'}]
right = [{'id': 1, 'val': 'x'}, {'id': 2, 'val': 'y'}, {'id': 3, 'val': 'z'}]
dt_left = sb.DataTree.from_records(left)
joined = dt_left.join(right, on='id')
out = [r.data for r, _ in joined.scan()]
check("join has 2 rows", len(out) == 2)
check("join merges", out[0] == {'id': 1, 'name': 'a', 'val': 'x'})

# ====== T10: chain ======
print("--- T10: chain (sbo.flatten + sbo.filter) ---")
recs = [{'tags': [[['ring'], [40, 44]], [['red'], [31, 34]]]}]
dt = sb.DataTree.from_records(recs)
pipeline = chain(sbo.flatten(b.tags, -1), sbo.filter(sbo._, lambda x: isinstance(x, str)))
dt2 = dt.expr(assign(b.flat_kept, pipeline))
out = [r.data for r, _ in dt2.scan()]
check("chain flatten+filter", out[0]['flat_kept'] == ['ring', 'red'])

# ====== T11: sort_by ======
print("--- T11: sort_by ---")
recs = [{'n': 3}, {'n': 1}, {'n': 2}]
dt = sb.DataTree.from_records(recs)
sorted_dt = dt.sort_by('n')
out = [r.data['n'] for r, _ in sorted_dt.scan()]
check("sort_by ascending", out == [1, 2, 3])

# ====== T12: No invertibility surface ======
print("--- T12: No invertibility ---")
dt = sb.DataTree.from_records([{'a': 1}])
check("no invert method", not hasattr(dt, 'invert'))
check("no invert_all method", not hasattr(dt, 'invert_all'))
check("no _history attr", not hasattr(dt, '_history'))
check("no _track attr", not hasattr(dt, '_track'))

print()
print(f"=== {passed} passed, {failed} failed ===")
sys.exit(0 if failed == 0 else 1)
