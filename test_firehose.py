def atproto_firehose_stream(limit=100, record_types=None):
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
                if record and record.get('\') in record_types:
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

for i in atproto_firehose_stream(limit=3):
    print(i['record'].get('text', '')[:50])
