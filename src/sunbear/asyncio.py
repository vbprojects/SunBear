"""
ADict — async entry point for sunbear.

An ADict wraps an awaitable that resolves to a dict (or list of dicts).
It bridges async data sources (HTTP, WebSocket, firehose streams) into
sunbear's synchronous DataTree pipeline.

Usage as a single-record proxy::

    adict = ADict(fetch_remote_config())
    value = await adict["some_key"]          # awaits, then indexes

Usage as an async record stream::

    async for record in ADict.stream(ait):
        print(record)

Conversion to DataTree::

    dt = await ADict.from_coroutine(coro).to_datatree()
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Awaitable, Dict, Optional, Sequence, Union


class ADict:
    """Async dict proxy — defers resolution until ``await`` or ``async for``.

    Parameters
    ----------
    awaitable : Awaitable[dict]
        A coroutine, Task, or Future that resolves to a dict.
    """

    def __init__(self, awaitable: Awaitable[Dict[Any, Any]]):
        self._awaitable = awaitable
        self._resolved: Optional[Dict[Any, Any]] = None

    # ── core dict-like interface ──────────────────────────────────────────

    async def _resolve(self) -> Dict[Any, Any]:
        if self._resolved is None:
            self._resolved = await self._awaitable
        return self._resolved

    async def __getitem__(self, key: Any) -> Any:
        data = await self._resolve()
        return data[key]

    async def __setitem__(self, key: Any, value: Any) -> None:
        data = await self._resolve()
        data[key] = value

    async def __contains__(self, key: Any) -> bool:
        data = await self._resolve()
        return key in data

    async def get(self, key: Any, default: Any = None) -> Any:
        data = await self._resolve()
        return data.get(key, default)

    async def keys(self):
        data = await self._resolve()
        return data.keys()

    async def values(self):
        data = await self._resolve()
        return data.values()

    async def items(self):
        data = await self._resolve()
        return data.items()

    # ── awaitable protocol ───────────────────────────────────────────────

    def __await__(self):
        """``data = await adict`` resolves to the underlying dict."""
        return self._resolve().__await__()

    # ── async iteration over a list of dicts ─────────────────────────────

    def __aiter__(self):
        """``async for record in adict:`` — iterates if the resolved value
        is a list of dicts (typical for stream results)."""
        return _ADictIterator(self)

    # ── factory constructors ─────────────────────────────────────────────

    @classmethod
    def from_coroutine(cls, coro) -> "ADict":
        """Wrap a bare coroutine (e.g. ``httpx.get(...)``)."""
        return cls(coro)

    @classmethod
    def from_value(cls, value: Dict[Any, Any]) -> "ADict":
        """Wrap an already-resolved dict (no await needed)."""
        fut = asyncio.get_event_loop().create_future()
        fut.set_result(value)
        return cls(fut)

    @classmethod
    def stream(cls, aiter: AsyncIterator[Dict[Any, Any]]) -> "ADictStream":
        """Wrap an async iterator as an ADictStream for ``async for``."""
        return ADictStream(aiter)

    # ── conversion to sync DataTree ──────────────────────────────────────

    async def to_datatree(self):
        """Resolve and build a ``DataTree``. Requires sunbear to be installed."""
        data = await self._resolve()
        from .tree import DataTree
        if isinstance(data, list):
            return DataTree.from_records(data)
        return DataTree.from_records([data])


class _ADictIterator:
    """Async iterator helper for ADict over list-of-dict results."""

    def __init__(self, adict: ADict):
        self._adict = adict
        self._index = 0

    async def __anext__(self):
        data = await self._adict._resolve()
        if not isinstance(data, list):
            raise TypeError("ADict value is not a list; cannot iterate")
        if self._index >= len(data):
            raise StopAsyncIteration
        item = data[self._index]
        self._index += 1
        return item


class ADictStream:
    """Async iterator wrapper — for wrapping firehose/WebSocket streams.

    Created via ``ADict.stream(async_iter)``.

    Supports ``async for`` and ``await .collect(n)`` to gather N records
    into a list (then into a DataTree).
    """

    def __init__(self, aiter: AsyncIterator[Dict[Any, Any]]):
        self._aiter = aiter

    def __aiter__(self):
        return self._aiter

    async def collect(self, limit: Optional[int] = None) -> list:
        """Collect records into a list, optionally capped at ``limit``."""
        results = []
        async for item in self._aiter:
            results.append(item)
            if limit is not None and len(results) >= limit:
                break
        return results

    async def to_datatree(self, limit: Optional[int] = None):
        """Collect records and build a DataTree."""
        from .tree import DataTree
        records = await self.collect(limit)
        return DataTree.from_records(records)
