from __future__ import annotations

import asyncio
import contextlib
import logging

from pytgcalls import PyTgCalls, filters
from pytgcalls.types import ChatUpdate, StreamEnded, Update

from noxy import userbot
from noxy.core.settings import AUTO_LEAVING_ASSISTANT

LOGGER = logging.getLogger(__name__)


class CallLifecycleMixin:
    async def start(self) -> None:
        LOGGER.info("Starting voice-call clients…")
        self._started.clear()

        if not self.calls:
            names = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
            call_pairs = []
            for session_string, slot, client in userbot.clients:
                call_client = PyTgCalls(client)
                call_pairs.append((session_string, call_client))
                self._by_slot[slot] = call_client
                setattr(self, names.get(slot, f"slot{slot}"), call_client)
            self.calls = tuple(call_pairs)

        async def _start_one(session: str, call: PyTgCalls):
            await call.start()
            return call

        pairs = [
            (session, call)
            for (session, call), client in zip(self.calls, userbot.clients, strict=False)
            if session
        ]
        try:
            results = await asyncio.gather(
                *(_start_one(session, call) for session, call in pairs),
                return_exceptions=True,
            )
        except asyncio.CancelledError:
            await asyncio.gather(
                *(call.stop() for _, call in pairs),
                return_exceptions=True,
            )
            self._started.clear()
            self.calls = ()
            self._by_slot.clear()
            raise

        for (_session, call), result in zip(pairs, results, strict=False):
            if isinstance(result, BaseException):
                LOGGER.error("Voice-call client failed to start: %s", result)
                with contextlib.suppress(Exception):
                    await call.stop()
                continue
            self._started.append(call)

        if not self._started:
            self.calls = ()
            self._by_slot.clear()
            raise RuntimeError("No PyTgCalls client could be started.")

        if AUTO_LEAVING_ASSISTANT and (
            self._auto_leave_task is None or self._auto_leave_task.done()
        ):
            self._auto_leave_task = asyncio.create_task(
                self._auto_leave_loop(), name="noximusic-auto-leave"
            )
        LOGGER.info("Voice-call clients ready: %d", len(self._started))

    async def stop(self) -> None:
        if self._auto_leave_task is not None:
            self._auto_leave_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._auto_leave_task
            self._auto_leave_task = None

        prefetch_tasks = list(self._prefetch_tasks.values())
        for task in prefetch_tasks:
            task.cancel()
        if prefetch_tasks:
            await asyncio.gather(*prefetch_tasks, return_exceptions=True)
        self._prefetch_tasks.clear()
        self._autoend.clear()

        failures = 0
        for call in reversed(self._started):
            try:
                await call.stop()
            except Exception:
                failures += 1
                LOGGER.exception("A voice-call client did not stop cleanly.")
        self._started.clear()
        if failures:
            LOGGER.warning("%d voice-call client(s) failed to stop.", failures)

    async def decorators(self) -> None:
        statuses = (
            ChatUpdate.Status.KICKED,
            ChatUpdate.Status.CLOSED_VOICE_CHAT,
            ChatUpdate.Status.LEFT_CALL,
        )

        async def on_chat_update(_, update: Update):
            await self.stop_stream(update.chat_id)

        async def on_stream_end(client, update: Update):
            await self._autoplay_fill(update.chat_id)
            await self.play(client, update.chat_id)

        for session, call in self.calls:
            if not session or call not in self._started:
                continue
            for status in statuses:
                call.on_update(filters.chat_update(status))(on_chat_update)
            for stream_type in (StreamEnded.Type.AUDIO, StreamEnded.Type.VIDEO):
                call.on_update(filters.stream_end(stream_type))(on_stream_end)
