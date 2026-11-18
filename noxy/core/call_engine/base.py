from __future__ import annotations

import asyncio

from pytgcalls import PyTgCalls

from noxy import db
from noxy.database import group_assistant, remove_active_chat, remove_active_video_chat

_MAX_LOCKS = 4096


class CallBase:
    def __init__(self) -> None:
        self.calls: tuple[tuple[str, PyTgCalls], ...] = ()
        self._by_slot: dict[int, PyTgCalls] = {}
        self._started: list[PyTgCalls] = []
        self._play_locks: dict[int, asyncio.Lock] = {}
        self._auto_leave_task: asyncio.Task | None = None
        self._autoend: dict[int, float] = {}
        self._autoplay_history: dict[int, list[str]] = {}
        self._consecutive_failures: dict[int, int] = {}
        self._prefetch_tasks: dict[int, asyncio.Task] = {}

    def lock(self, chat_id: int) -> asyncio.Lock:
        lock = self._play_locks.get(chat_id)
        if lock is None:
            if len(self._play_locks) >= _MAX_LOCKS:
                for stale in [
                    key for key, value in self._play_locks.items() if not value.locked()
                ]:
                    del self._play_locks[stale]
                    if len(self._play_locks) < _MAX_LOCKS // 2:
                        break
            lock = self._play_locks[chat_id] = asyncio.Lock()
        return lock

    async def assistant(self, chat_id: int) -> PyTgCalls:
        return await group_assistant(self, chat_id)

    def for_slot(self, slot: int) -> PyTgCalls | None:
        client = self._by_slot.get(int(slot))
        return client if client in self._started else None

    @staticmethod
    def _bot():
        from noxy import app

        return app

    async def _clear(self, chat_id: int) -> None:
        db[chat_id] = []
        self._autoend.pop(chat_id, None)
        self._autoplay_history.pop(chat_id, None)
        self._consecutive_failures.pop(chat_id, None)
        await remove_active_video_chat(chat_id)
        await remove_active_chat(chat_id)
