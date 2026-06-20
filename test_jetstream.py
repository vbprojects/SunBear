import json
import websocket

def fetch_jetstream_stream(limit=100, record_types=None):
    if record_types is None:
        record_types = ['app.bsky.feed.post']

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
            
            # Jetstream messages can be 'commit', 'identity', 'account'
            if data.get('kind') == 'commit':
                commit = data.get('commit', {})
                if commit.get('operation') == 'create':
                    record = commit.get('record')
                    if record and record.get('type') in record_types:
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

for i in fetch_jetstream_stream(limit=3):
    print(i['record'].get('text', '')[:50])
