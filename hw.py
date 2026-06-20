# %%
# from DataTree import DataTree as sb
# %%
import json

import websocket

import sunbear as sb
from sunbear import DataTree


def fetch_jetstream_stream(limit=100, record_types=None):
    if record_types is None:
        record_types = ["app.bsky.feed.post"]

    # Using jetstream public instance
    url = "wss://jetstream2.us-east.bsky.network/subscribe"

    # We can ask Jetstream to filter collections for us to save bandwidth!
    collections = "&".join([f"wantedCollections={t}" for t in record_types])
    ws_url = f"{url}?{collections}"

    ws = websocket.create_connection(ws_url)

    count = 0
    try:
        while limit is None or count < limit:
            msg = ws.recv()
            if not msg:
                break

            data = json.loads(msg)
            yield data
            count += 1
    finally:
        ws.close()


js = []
for i in fetch_jetstream_stream(limit=1000):
    js.append(i)

# %%
dt = sb.DataTree.from_records(js)
# %%
# from Schema import Schema
dt.inspect("commit.record.facets")
# %%
dt.pluck("commit.record.facets")
# %%
import sunbear.ops as sbo
from sunbear.expr import assign, b, keep, _
from datetime import datetime
# %%
res = dt.select(facets=b.commit.record.facets, text = b.commit.record.text, createdAt = b.commit.record.createdAt).expr(
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
    b.facets(lambda fs: [f[1] for f in fs if isinstance(f, list) and "#tag" in f[0]]),
).col(text = b.text, createdAt = b.createdAt, tags = b.facets)
# %%
res
# %%
