from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Hashable
from typing import Any, Generic, TypeVar

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")


class TTLCache(Generic[K, V]):
    __slots__ = ("_data", "_locks", "_max_entries", "_prune_at", "_ttl")

    def __init__(self, *, ttl: float, max_entries: int = 512) -> None:
        self._data: dict[K, tuple[float, V]] = {}
        self._locks: dict[K, asyncio.Lock] = {}
        self._ttl = ttl
        self._max_entries = max_entries
        self._prune_at = max(16, max_entries // 2)

    def get(self, key: K) -> V | None:
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: K, value: V, ttl: float | None = None) -> None:
        if len(self._data) >= self._max_entries:
            self._prune()
        self._data[key] = (time.monotonic() + (ttl if ttl is not None else self._ttl), value)

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [key for key, (expires, _) in self._data.items() if expires <= now]
        for key in expired:
            self._data.pop(key, None)

        overflow = len(self._data) - self._max_entries + 1
        for _ in range(max(0, overflow)):
            if not self._data:
                break
            self._data.pop(next(iter(self._data)), None)
        self._locks.clear()

    def clear(self) -> None:
        self._data.clear()
        self._locks.clear()

    def __len__(self) -> int:
        return len(self._data)

    async def memoize(
        self,
        key: K,
        factory: Callable[[], Any],
        *,
        ttl: float | None = None,
        copy: Callable[[V], Any] | None = None,
    ) -> Any:
        cached = self.get(key)
        if cached is not None:
            return copy(cached) if copy else cached

        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()

        async with lock:
            cached = self.get(key)
            if cached is not None:
                return copy(cached) if copy else cached

            value = factory()
            if asyncio.iscoroutine(value):
                value = await value
            if value is not None:
                self.set(key, value, ttl=ttl)
            return value

    def pop(self, key: K) -> V | None:
        item = self._data.pop(key, None)
        self._locks.pop(key, None)
        return None if item is None else item[1]
