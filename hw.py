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
import sunbear.ops as sbo
from sunbear.expr import _, assign, b, keep

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
# %%
while True:
    res = (
        sb.DataTree.from_records(next(batched(jetstream_generator(), 200)))
        .untracked()
        .select(
            facets=b.commit.record.facets,
            text=b.commit.record.text,
            createdAt=b.commit.record.createdAt,
            id=b.commit.cid,
        )
        .expr(
            keep(
                sbo.length(
                    sbo.chain(
                        sbo.flatten(b.facets, -1),
                        sbo.filter(_, lambda x: isinstance(x, str) and "#tag" in x),
                    ),
                )
                > 0
            ),
            b.createdAt(lambda t: datetime.fromisoformat(t)),
            assign(b.facets, sbo.flatten(b.facets, 3)),
            b.facets(
                lambda fs: [f[1] for f in fs if isinstance(f, list) and "#tag" in f[0]]
            ),
        )
        .explode("facets")
        .col(text=b.text, createdAt=b.createdAt, tag=b.facets, id=b.id)
    )
    for tag, createdAt in zip(res["tag"], res["createdAt"]):
        model[tag].update(createdAt)
    # get top 10 tags by mean
    top_tags = sorted(model.items(), key=lambda x: x[1].mean, reverse=True)[:10]
    # print(f"Top tags at {datetime.now(timezone.utc)}:")
    # Move cursor up to overwrite previous output
    print(f"\033[{len(top_tags)}A", end="")

    cols = shutil.get_terminal_size().columns
    from IPython.display import clear_output
    msg = ""
    for tag, m in top_tags:
        line = f"  {tag}: mean={m.mean:.2f}, variance={m.variance:.2f}"
        msg += line.ljust(cols) + "\n"
    clear_output(wait=True)
    print(msg)
# %%
import time

for i in range(11):
    # \r resets cursor, end="" prevents new lines, flush=True updates instantly
    print(f"\rProgress: {i*10}%", end="", flush=True)
    time.sleep(0.5)
print("\nDone!")
# %%
for tag, m in model.items():
    print(f"{tag}: mean={m.mean:.2f}, variance={m.variance:.2f}, total count = {m.alpha:.0f}")
# %%
model["ai"].times
# %%