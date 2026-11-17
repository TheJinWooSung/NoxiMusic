from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Hashable
from typing import Any, Generic, TypeVar

LOGGER = logging.getLogger(__name__)

K = TypeVar("K", bound=Hashable)
V = TypeVar("V")

DEFAULT_MAX_ENTRIES = 4096


class HotCache(Generic[K, V]):
    __slots__ = ("_data", "_max")

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._data: OrderedDict[K, V] = OrderedDict()
        self._max = max_entries

    def get(self, key: K, default: Any = None) -> Any:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return default

    def __contains__(self, key: K) -> bool:
        return key in self._data

    def set(self, key: K, value: V) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        if len(self._data) > self._max:
            self._data.popitem(last=False)

    def pop(self, key: K, default: Any = None) -> Any:
        return self._data.pop(key, default)

    def clear(self) -> None:
        self._data.clear()

    def keys(self):
        return list(self._data.keys())

    def __len__(self) -> int:
        return len(self._data)


class WriteThroughCache(Generic[K]):
    __slots__ = ("_max", "_members")

    def __init__(self, max_entries: int = DEFAULT_MAX_ENTRIES) -> None:
        self._members: OrderedDict[K, None] = OrderedDict()
        self._max = max_entries

    def add(self, item: K) -> bool:
        if item in self._members:
            return False
        self._members[item] = None
        self._members.move_to_end(item)
        if len(self._members) > self._max:
            self._members.popitem(last=False)
        return True

    def discard(self, item: K) -> bool:
        return self._members.pop(item, ...) is not ...

    def __contains__(self, item: K) -> bool:
        return item in self._members

    def clear(self) -> None:
        self._members.clear()

    def snapshot(self) -> list[K]:
        return list(self._members.keys())

    def __len__(self) -> int:
        return len(self._members)

_background_tasks: set[asyncio.Task] = set()


def spawn_background(coro, *, name: str | None = None) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def drain_background_tasks() -> None:
    if not _background_tasks:
        return
    pending = list(_background_tasks)
    results = await asyncio.gather(*pending, return_exceptions=True)
    for result in results:
        if isinstance(result, Exception):
            LOGGER.debug("Background database task failed", exc_info=result)
