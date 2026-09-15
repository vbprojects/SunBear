# %%
# from DataTree import DataTree as sb
# %%
import json

import websocket

import sunbear as sb
from sunbear import DataTree


def jetstream_generator(limit=None, record_types=None):
    """Yield decoded Jetstream messages one at a time.

    Yields parsed JSON dicts for each message received over the
    Jetstream WebSocket. The connection is auto-closed when the
    generator is exhausted or garbage-collected.
    """
    if record_types is None:
        record_types = ["app.bsky.feed.post"]

    collections = "&".join(f"wantedCollections={t}" for t in record_types)
    ws = websocket.create_connection(
        f"wss://jetstream2.us-east.bsky.network/subscribe?{collections}"
    )

    try:
        count = 0
        while limit is None or count < limit:
            msg = ws.recv()
            if not msg:
                break
            yield json.loads(msg)
            count += 1
    finally:
        ws.close()
#%%
next(jetstream_generator())

# %%
from datetime import datetime, timezone
from itertools import batched
import shutil
from sunbear.expr import _, assign, b, keep, sbo

start_time = datetime.now(timezone.utc)

from datetime import datetime, timezone

class gptd:
    """Gamma Poisson Model with time discounting"""

    def __init__(self, alpha=1.0, beta=1.0, discount_rate=1/3600):
        self.alpha = alpha
        self.beta = beta
        self.gamma = 1 - discount_rate
        self.last_time = None
        self.times = []

    def update(self, time, count=1):
        if self.last_time is not None:
            time_diff = (time - self.last_time).total_seconds() / 60
            discount_factor = self.gamma**time_diff
            
            self.alpha *= discount_factor
            self.beta *= discount_factor
            
            self.alpha += count
            self.beta += time_diff # <-- Changed to time_diff
            self.times.append(time)
        else:
            # Handle the very first observation if last_time was initialized as None
            self.alpha += count
            self.times.append(time)
            # Without a prior time, you might need a default observation window, or ignore beta addition
            
        self.last_time = time

    @property
    def mean(self):
        self.update(datetime.now(timezone.utc), count = 0)
        return self.alpha / self.beta

    @property
    def variance(self):
        return self.alpha / (self.beta**2)
from collections import defaultdict
model = defaultdict(gptd)
#%%
batch = next(batched(jetstream_generator(), 100))
#%%
dt = DataTree.from_records(batch)
# %%
dt.infer_schema(sample=100).schema
# dt.select(facets = b.commit.record.facets).head().pluck(b.facets)
dt.expr(
    assign(b.facets, b.commit.record.facets),
    keep(b.facets.is_not_null()),
).head().pluck(b.facets)[0]
# %%
dt.infer_schema(sample=100).schema
#%%
dt.expr(
    assign(b.feats, b.commit.record.facets.features['$type']),
    keep(b.feats.is_not_null()),
    assign(b.feats, sbo.flatten(b.feats))
).pluck(b.feats)
# %%
dt.pluck(b.commit.record.facets.features['$type'])
#%%
dt.inspect(b.commit.record.facets.features)
#%%
dt.pluck(b.commit.record.createdAt)
#%%
dt.infer_schema(sample=100).schema
#%%
from sunbear.Program import Program
#%%
prog = Program().expr(
    assign(b.tags, b.commit.record.facets.features.tag),
    assign(b.createdAt, b.commit.record.createdAt),
    keep(b.tags.is_not_null()),
    assign(b.tags, sbo.flatten(b.tags)),
    keep(b.createdAt.is_not_null())
)
# %%
dt = DataTree.from_iter(jetstream_generator())
#%%
prog(dt)
#%%
tag_collector = prog(dt).irows(tags = b.tags, createdAt = b.createdAt)
#%%
next(tag_collector)
# %%
dt = DataTree.from_iter(jetstream_generator())
prog(dt)

#%%
sb.write_jsonl(prog(dt).head(100), "jetstream-tags.jsonl")
saved_tags = sb.read_jsonl("jetstream-tags.jsonl")