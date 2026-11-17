from __future__ import annotations

import asyncio

import pytest

from noxy.database.cache import HotCache, WriteThroughCache
from noxy.services.cache import TTLCache


def test_hot_cache_tracks_size_and_lru_order():
    cache: HotCache[int, str] = HotCache(max_entries=2)
    cache.set(1, "a")
    cache.set(2, "b")
    assert cache.get(1) == "a"

    cache.set(3, "c")
    assert 2 not in cache
    assert cache.get(3) == "c"
    assert len(cache) == 2


def test_write_through_cache_add_and_discard():
    members: WriteThroughCache[int] = WriteThroughCache(max_entries=4)
    assert members.add(10) is True
    assert members.add(10) is False
    assert 10 in members
    assert members.discard(10) is True
    assert 10 not in members
    assert members.snapshot() == []


@pytest.mark.asyncio
async def test_ttl_cache_memoises_and_expires():
    calls = 0

    async def factory():
        nonlocal calls
        calls += 1
        return {"value": calls}

    cache: TTLCache[str, dict] = TTLCache(ttl=60)
    first = await cache.memoize("k", factory)
    second = await cache.memoize("k", factory)
    assert first == second == {"value": 1}
    assert calls == 1

    short: TTLCache[str, int] = TTLCache(ttl=0.01)
    await short.memoize("k", lambda: 1)
    await asyncio.sleep(0.02)
    assert await short.memoize("k", lambda: 2) == 2


@pytest.mark.asyncio
async def test_ttl_cache_coalesces_concurrent_misses():
    started = asyncio.Event()

    async def slow_factory():
        started.set()
        await asyncio.sleep(0.05)
        return "value"

    cache: TTLCache[str, str] = TTLCache(ttl=60)
    results = await asyncio.gather(
        *(cache.memoize("key", slow_factory) for _ in range(20))
    )
    assert results == ["value"] * 20
    assert started.is_set()
