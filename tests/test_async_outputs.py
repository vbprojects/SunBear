import asyncio
import tempfile
import unittest
import sunbear as sb
from sunbear import f, emit, targets


class AsyncOutputTests(unittest.IsolatedAsyncioTestCase):
    async def test_incremental_reuses_transform_and_closes_source(self):
        seen = []
        closed = []

        async def source():
            try:
                i = 0
                while True:
                    seen.append(i)
                    yield {"x": i}
                    i += 1
            finally:
                closed.append(True)

        job = (
            sb.Program()
            .where(f.x % 2 == 0)
            .assign(y=f.x + 1)
            .emit(emit.document("posts"))
            .compile(targets.jsonl())
        )
        output = job.astream(source(), batch_rows=2)
        batch = await anext(output)
        self.assertEqual(batch.operation_count, 2)
        self.assertIn('"y":1', batch.text)
        self.assertLessEqual(len(seen), 5)
        await output.aclose()
        self.assertEqual(closed, [True])

    async def test_async_cache_is_batched_and_flushed(self):
        with tempfile.TemporaryDirectory() as d:
            calls = []

            def fn(value):
                calls.append(value)
                return value + 1

            p = sb.Program(
                cache=sb.cache.FileCache("async", directory=d), cache_version="v1"
            ).assign(y=f.x.apply(fn))

            async def source():
                for x in [1, 1, 2]:
                    yield {"x": x}

            job = p.emit(emit.row("posts")).compile(targets.jsonl())
            result = [b async for b in job.astream(source())]
            self.assertEqual(sum(b.operation_count for b in result), 3)
            self.assertEqual(calls, [1, 2])
            self.assertEqual(p._cache._pending, 0)

    async def test_cancellation_closes_source(self):
        started = asyncio.Event()
        closed = []

        async def source():
            try:
                started.set()
                await asyncio.Event().wait()
                yield {}
            finally:
                closed.append(True)

        output = (
            sb.Program()
            .emit(emit.document("posts"))
            .compile(targets.jsonl())
            .astream(source())
        )
        task = asyncio.create_task(anext(output))
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(closed, [True])
