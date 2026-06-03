#%%
import urllib.request
import json
import time
import random
from pathlib import Path
from sunbear.DataTree import DataTree
from sunbear.Schema import infer_schema, Path
from functools import cache

@cache
def fetch_bluesky_feed_stream(
    actor=None,
    endpoint="getTimeline",
    limit=100,
    max_pages=10,
    max_retries=3,
    base_delay=1.0,
    backoff_factor=2.0,
    sleep_between_pages=0.5,
):
    """Stream BlueSky feed records as a generator with pagination, retries, and backoff.

    Yields individual feed post dicts.

    Parameters
    ----------
    actor : str, optional
        Only used with endpoint="getAuthorFeed".
    endpoint : str
        One of "getTimeline", "getAuthorFeed", "getPopularFeed".
        Defaults to "getTimeline" — a diverse feed of recent posts.
    """
    cursor = None
    pages_fetched = 0
    feed_count = 0

    while pages_fetched < max_pages:
        base = f"https://public.api.bsky.app/xrpc/app.bsky.feed.{endpoint}"
        params = f"limit={limit}"
        if endpoint == "getAuthorFeed":
            if actor is None:
                actor = "bsky.app"
            params += f"&actor={actor}"
        if cursor:
            params += f"&cursor={cursor}"
        url = f"{base}?{params}"

        last_error = None
        for attempt in range(max_retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = json.loads(response.read().decode("utf-8"))
                last_error = None
                break
            except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    delay = base_delay * (backoff_factor ** attempt) + random.uniform(0, 0.5)
                    print(f"  [retry {attempt + 1}/{max_retries}] {e} — waiting {delay:.1f}s...")
                    time.sleep(delay)

        if last_error is not None:
            print(f"  [gave up after {max_retries} retries] {last_error}")
            return

        feed_batch = data.get("feed", [])
        cursor = data.get("cursor")
        pages_fetched += 1

        for item in feed_batch:
            feed_count += 1
            yield item

        print(f"  page {pages_fetched}: {len(feed_batch)} posts (total: {feed_count})")

        if not cursor:
            print("  no more pages.")
            break

        if pages_fetched < max_pages:
            time.sleep(sleep_between_pages)

def fetch_bluesky_firehose_stream(limit=100, record_types=None):
    """Stream BlueSky firehose records as a generator."""
    from atproto import FirehoseSubscribeReposClient, parse_subscribe_repos_message, models, CAR
    import queue
    import threading

    if record_types is None:
         record_types = ['app.bsky.feed.post']

    client = FirehoseSubscribeReposClient()
    q = queue.Queue(maxsize=100)
    stop_event = threading.Event()

    def on_message_handler(message):
        if stop_event.is_set():
            client.stop()
            return
            
        commit = parse_subscribe_repos_message(message)
        if not isinstance(commit, models.ComAtprotoSyncSubscribeRepos.Commit):
            return
        if not commit.blocks: 
            return
            
        car = CAR.from_bytes(commit.blocks)
        for op in commit.ops:
            if op.action == 'create':
                record = car.blocks.get(op.cid)
                if record and record.get('$type') in record_types:
                    try:
                        q.put({
                            'repo': commit.repo,
                            'path': op.path,
                            'cid': str(op.cid),
                            'record': record
                        }, block=False)
                    except queue.Full:
                        pass

    def run_client():
        try:
            client.start(on_message_handler)
        except Exception:
            pass

    t = threading.Thread(target=run_client, daemon=True)
    t.start()

    count = 0
    try:
        while limit is None or count < limit:
            item = q.get()
            yield item
            count += 1
    finally:
        stop_event.set()

def fetch_jetstream_stream(limit=100, record_types=None):
    """Stream BlueSky firehose records using Jetstream (JSON over WebSockets)."""
    import json
    import websocket # Requires: pip install websocket-client

    if record_types is None:
        record_types = ['app.bsky.feed.post']

    # Using an official Jetstream public instance
    url = "wss://jetstream2.us-east.bsky.network/subscribe"
    
    # Ask Jetstream to pre-filter collections to save bandwidth
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
            
            # Jetstream messages can be 'commit', 'identity', 'account'
            if data.get('kind') == 'commit':
                commit = data.get('commit', {})
                if commit.get('operation') == 'create':
                    record = commit.get('record')
                    # Double check type just in case
                    if record and record.get('$type') in record_types:
                        item = {
                            'repo': data.get('did'),
                            'path': commit.get('collection') + '/' + commit.get('rkey'),
                            'cid': commit.get('cid'),
                            'record': record
                        }
                        yield item
                        count += 1
    finally:
        ws.close()

# Load feed: prefer cached file, otherwise stream from API and cache
# feed_path = Path("bluesky_feed.json")

# if feed_path.exists():
#     print("Loading data from local file...")
#     with open(feed_path, "r") as f:
#         feed = json.load(f)
# else:
#     print("Streaming feed from Bluesky API...")
#     feed = list(fetch_bluesky_feed_stream(limit=100, max_pages=50))
#     with open(feed_path, "w") as f:
#         json.dump(feed, f, indent=2)
#     print(f"Cached {len(feed)} posts to bluesky_feed.json")
#%%
# feed = list(fetch_bluesky_feed_stream(limit=100, max_pages=50))
# Clean and flatten feed into records for DataTree
dt = DataTree(
    fetch_jetstream_stream(limit=100), 
    defer_evaluation=True
)
print("Streaming author feed (bsky.app)...")
#%%
from sunbear.DataBranch import DataBranch
@DataTree.register_method
@DataBranch.register_method
def head(db, n=5, return_tree=False):
    """Return the first N records."""
    import itertools
    dbt = DataBranch(db, operation=lambda r: list(itertools.islice(r, n)))
    if return_tree:
        dbt.return_tree = True
    return dbt

@DataTree.register_method
@DataBranch.register_method
def chain(db, func):
    return DataBranch(db, operation=func)

#%%
dt.head(return_tree=True, n=5).collect().mat.show(collapsed=True)
@DataTree.register_method
@DataBranch.register_method
def select(db, **kwargs):
    """Select and rename paths in a single pass using primitive map_records."""
    from sunbear.utils import col
    for k, v in kwargs.items():
        if isinstance(v, str):
            v = col(v)
        db = db[:, k].assign(v)
    return db.path(list(kwargs.keys()))
#%%
def flatten(x):
    return [item for sublist in x for item in (flatten(sublist) if isinstance(sublist, list) else [sublist])]
#%%
from copy import deepcopy
# dtb = deepcopy(dt)
dt[:, ['cid', 'record.facets.features.$type']].collect()
# dtb.chain(deepcopy).path('record.facets.features.$type')[:, '$type'].not_(lambda x: x is None).shallow(flatten).not_(lambda x: all(v is None for v in x)).collect()
#%%
dt
# %%

# %%

# %%
dt.path('record.embed').head().collect()
#%%
dt.head().path("post.record.facets.features.tag")
#%%
# Test select
dt.select(uri="post.uri", text="post.record.text").head().collect()
#%%
dt.head().select(uri="post.uri", text="post.record.text").collect()
#%%
dt.head(n=100).path(["post.record.facets.features.tag", "post.record.createdAt"])[:, "tag"].not_(lambda x: x is None).shallow(flatten).not_(lambda x: all(v is None for v in x))[:, ["tag", "createdAt"]].explode()[:, "tag"].not_(lambda x: x is None)[:, ["tag", "createdAt"]].collect()
# %%
