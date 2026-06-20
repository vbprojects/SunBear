"""
laws.py — property-based round-trip tests for DataTree operator classes.

Each operator is a BiOp = (forward, backward) where:
    forward(state) -> (new_state, complement)
    backward(new_state, complement) -> state

State is a list of twigs [(Record, metadata_dict), ...].
Generated twigs always carry a unique metadata["index"], which is the
load-bearing field for recovering *order* (the "= vs ≡" distinction).
"""

from __future__ import annotations
import copy
from typing import Callable, Any, List, Tuple
from hypothesis import given, strategies as st, settings, HealthCheck

# ---------------------------------------------------------------------------
# Minimal Record shim — replace with: from datatree import Record
# ---------------------------------------------------------------------------
class Record:
    def __init__(self, data: dict):
        self.data = data
    def __repr__(self):
        return f"Record({self.data!r})"

Twig = Tuple[Record, dict]
State = List[Twig]
_MISSING = object()

# ---------------------------------------------------------------------------
# Canonical form & equality (order-sensitive; dicts compare order-insensitively)
# ---------------------------------------------------------------------------
def canon(state: State):
    return [(r.data, m) for r, m in state]

def eq(a: State, b: State) -> bool:
    return canon(a) == canon(b)

# ---------------------------------------------------------------------------
# The two universal laws
# ---------------------------------------------------------------------------
def assert_recover(op, state: State):
    """L1: backward(forward(D)) == D"""
    original = copy.deepcopy(canon(state))           # snapshot before any work
    fwd, bwd = op
    new_state, complement = fwd(copy.deepcopy(state))
    recovered = bwd(new_state, complement)
    assert canon(recovered) == original, (
        f"L1 violated:\n  before={original}\n  after ={canon(recovered)}"
    )

def assert_stable(op, state: State):
    """L2: forward is idempotent through an undo (no drift on the image)."""
    fwd, bwd = op
    d1, c1 = fwd(copy.deepcopy(state))
    d2 = bwd(copy.deepcopy(d1), c1)
    d3, _ = fwd(d2)
    assert canon(d1) == canon(d3), (
        f"L2 violated:\n  f(D)   ={canon(d1)}\n  f(b(fD))={canon(d3)}"
    )

# ===========================================================================
# Reference operator pairs (these SATISFY the laws — your real ops go here)
# ===========================================================================

# --- 1. Row map (set with undo complement; self-dual class) ----------------
def rowmap_set(key: str, value: Any):
    def fwd(state):
        out = []
        for r, m in state:
            old = r.data.get(key, _MISSING)
            out.append((Record({**r.data, key: value}),
                        {**m, "_undo": old}))
        return out, None
    def bwd(state, _c):
        out = []
        for r, m in state:
            old = m["_undo"]
            d = dict(r.data)
            if old is _MISSING:
                d.pop(key, None)
            else:
                d[key] = old
            out.append((Record(d), {k: v for k, v in m.items() if k != "_undo"}))
        return out
    return fwd, bwd

# --- 2. Filter (complement = dropped rows + original positions) ------------
def filter_op(pred: Callable[[Record, dict], bool]):
    def fwd(state):
        kept, dropped = [], []
        for i, (r, m) in enumerate(state):
            (kept if pred(r, m) else dropped.append).__self__  # noqa (see below)
        # explicit form (clearer than the trick above):
        kept, dropped = [], []
        for i, (r, m) in enumerate(state):
            if pred(r, m):
                kept.append((r, m))
            else:
                dropped.append((i, (r, m)))
        return kept, dropped
    def bwd(state, dropped):
        out = list(state)
        for i, twig in dropped:        # dropped is ascending in i
            out.insert(i, twig)
        return out
    return fwd, bwd

# --- 3. Insertion (complement = provenance tag; inverse is a filter) -------
def insertion_op(new_twigs: State):
    tag = object()
    def fwd(state):
        tagged = [(r, {**m, "_ins": id(tag)}) for r, m in new_twigs]
        return list(state) + tagged, id(tag)
    def bwd(state, t):
        return [(r, m) for r, m in state if m.get("_ins") != t]
    return fwd, bwd

# --- 4. Explode (1->n) inverted by group+reassemble (n->1) -----------------
def explode_op(key: str):
    def fwd(state):
        out, comp = [], []
        for r, m in state:
            pidx = m["index"]
            vals = list(r.data.get(key, []))
            base = {k: v for k, v in r.data.items() if k != key}
            comp.append((pidx, base, m))           # record EVERY parent (handles empty lists)
            for pos, v in enumerate(vals):
                out.append((Record({**base, key: v}),
                            {**m, "parent": pidx, "pos": pos}))
        return out, comp
    def bwd(state, comp):
        groups: dict = {}
        for r, m in state:
            groups.setdefault(m["parent"], []).append((m["pos"], r.data[key]))
        out = []
        for pidx, base, pmeta in comp:
            vals = [v for _, v in sorted(groups.get(pidx, []))]
            out.append((Record({**base, key: vals}), pmeta))
        return out
    return fwd, bwd

# --- 5. Reduce/group (n->1) inverted by explode/unnest (1->n) --------------
def group_op(keyfn: Callable[[Record, dict], Any]):
    def fwd(state):
        groups, order = {}, []
        for r, m in state:
            k = keyfn(r, m)
            if k not in groups:
                groups[k] = []
                order.append(k)
            groups[k].append((dict(r.data), dict(m)))   # nest members (the complement)
        out = [(Record({"group": k, "members": groups[k]}), {"index": gi})
               for gi, k in enumerate(order)]
        return out, None
    def bwd(state, _c):
        restored = []
        for r, _m in state:
            for data, meta in r.data["members"]:
                restored.append((Record(dict(data)), dict(meta)))
        restored.sort(key=lambda t: t[1]["index"])       # recover order via kept index
        return restored
    return fwd, bwd

# --- 6. Join (n->m) inverted by join (m->n); complement = unmatched-left ----
def join_op(right: List[dict], on: str, right_cols: List[str]):
    def fwd(state):
        rindex: dict = {}
        for rr in right:
            rindex.setdefault(rr[on], []).append(rr)
        out, unmatched = [], []
        for r, m in state:
            matches = rindex.get(r.data.get(on), [])
            if not matches:                               # TOTALITY: stash dropped left rows
                unmatched.append((m["index"], (r, m)))
                continue
            for j, rr in enumerate(matches):
                merged = {**r.data, **{c: rr[c] for c in right_cols}}
                out.append((Record(merged), {**m, "_src": m["index"]}))
        return out, unmatched
    def bwd(state, unmatched):
        seen: dict = {}
        for r, m in state:
            li = m["_src"]
            if li in seen:                                # PROVENANCE: collapse fan-out
                continue
            base = {k: v for k, v in r.data.items() if k not in right_cols}
            meta = {k: v for k, v in m.items() if k != "_src"}
            seen[li] = (Record(base), meta)
        out = list(seen.values()) + [t for _, t in unmatched]
        out.sort(key=lambda t: t[1]["index"])
        return out
    return fwd, bwd

# ===========================================================================
# Hypothesis strategies for valid trees
# ===========================================================================
@st.composite
def trees(draw, max_rows=6):
    n = draw(st.integers(min_value=0, max_value=max_rows))
    state = []
    for i in range(n):
        data = {
            "id": i,
            "x": draw(st.integers(-5, 5)),
            "k": draw(st.sampled_from(["a", "b", "c"])),
            "vals": draw(st.lists(st.integers(0, 3), max_size=3)),
        }
        state.append((Record(data), {"index": i}))
    return state

@st.composite
def right_tables(draw):
    n = draw(st.integers(min_value=0, max_value=4))
    return [{"k": draw(st.sampled_from(["a", "b", "c"])),
             "rc": draw(st.integers(0, 9))} for _ in range(n)]

CFG = settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])

# ===========================================================================
# Tests — each class gets L1 (Recover) and L2 (Stability)
# ===========================================================================
@CFG
@given(d=trees(), v=st.integers(-9, 9))
def test_rowmap(d, v):
    op = rowmap_set("x", v)
    assert_recover(op, d); assert_stable(op, d)

@CFG
@given(d=trees(), thresh=st.integers(-5, 5))
def test_filter(d, thresh):
    op = filter_op(lambda r, m: r.data["x"] > thresh)
    assert_recover(op, d); assert_stable(op, d)

@CFG
@given(d=trees(), extra=st.lists(st.integers(0, 3), max_size=3))
def test_insertion(d, extra):
    new = [(Record({"id": 1000 + j, "x": v, "k": "z", "vals": []}),
            {"index": 1000 + j}) for j, v in enumerate(extra)]
    op = insertion_op(new)
    assert_recover(op, d); assert_stable(op, d)

@CFG
@given(d=trees())
def test_explode(d):
    op = explode_op("vals")
    assert_recover(op, d); assert_stable(op, d)

@CFG
@given(d=trees())
def test_group(d):
    op = group_op(lambda r, m: r.data["k"])
    assert_recover(op, d); assert_stable(op, d)

@CFG
@given(d=trees(), right=right_tables())
def test_join(d, right):
    op = join_op(right, on="k", right_cols=["rc"])
    assert_recover(op, d); assert_stable(op, d)

if __name__ == "__main__":
    import pytest, sys
    sys.exit(pytest.main([__file__, "-q"]))