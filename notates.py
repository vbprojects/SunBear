#%%
import urllib.request
import json
import time
import random
from pathlib import Psath
from sunbear.DataTree import DataTree
from sunbear.Schema import infer_schema

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
    fetch_bluesky_feed_stream(endpoint="getAuthorFeed", actor="bsky.app", limit=100, max_pages=50),
    defer_evaluation=True,
)
print("Streaming author feed (bsky.app)...")
#%%
from src.DataBranch import DataBranch
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

@DataTree.register_method
@DataBranch.register_method
def explode(db, column_path=None):
    col_idx = getattr(db, 'projection_col', None)
    if col_idx is None or not isinstance(col_idx, list):
        raise TypeError("explode() requires a breadth projection with at least 2 columns")

    # Resolve column names (strings) from the projection
    col_names = []
    for c in col_idx:
        if isinstance(c, str):
            col_names.append((c, None))  # (name, depth_path)
        elif isinstance(c, tuple):
            col_names.append((c[-1], c))
        else:
            col_names.append((None, c))

    def op(records):
        import copy
        for r in records:
            # Detect whether records are dicts or lists
            if isinstance(r, dict):
                # Find the first column whose value is a list
                exploded_key = None
                for name, _ in col_names:
                    val = r.get(name) if name else None
                    if isinstance(val, list):
                        exploded_key = name
                        break
                if exploded_key is None:
                    yield copy.deepcopy(r)
                    continue

                items = r[exploded_key]
                if not items:
                    continue

                for item in items:
                    row = copy.deepcopy(r)
                    row[exploded_key] = item
                    yield row

            elif isinstance(r, (list, tuple)):
                # Legacy list-format records
                exploded_idx = None
                for i in range(len(r)):
                    if isinstance(r[i], list):
                        exploded_idx = i
                        break
                if exploded_idx is None:
                    yield copy.deepcopy(r)
                    continue

                items = r[exploded_idx]
                if not items:
                    continue

                for item in items:
                    row = copy.deepcopy(r)
                    row[exploded_idx] = item
                    yield row
            else:
                yield copy.deepcopy(r)

    branch = DataBranch(db, operation=op)
    branch.return_tree = True
    return branch

# #%%
# schemas = dt.schemas()
# schemas[1].diff(schemas[3])
# dt[:, tuple("post.labels".split("."))].shallow(lambda x: len(x) > 1).collect()
# # %%
# schemas[1].show(collapsed=True)
# #%%
# dt.head().show(collapsed=True)
# # %%
# dt.show(collapsed=True)
#%%
dt.head(return_tree=True, n=5).collect().mat.show(collapsed=True)
#%%
def flatten(x):
    return [item for sublist in x for item in (flatten(sublist) if isinstance(sublist, list) else [sublist])]
#%%
dt.path(["post.record.facets.features.tag", "post.record.createdAt"])[:, "tag"].not_(lambda x: x is None).shallow(flatten).not_(lambda x: all(v is None for v in x))[:, ["tag", "createdAt"]].explode()[:, "tag"].not_(lambda x: x is None)[:, ["tag", "createdAt"]].collect()
# %%