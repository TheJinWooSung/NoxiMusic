from __future__ import annotations

import asyncio
import contextlib
import logging

from noxy import db
from noxy.core.settings import AUTO_LEAVING_ASSISTANT, PREFETCH_COUNT, PREFETCH_ENABLED
from noxy.database import get_active_chats, get_autoplay, get_playmode
from noxy.services.track import QueueItem

LOGGER = logging.getLogger(__name__)


class CallAutomationMixin:
    def _schedule_prefetch(self, chat_id: int) -> None:
        if not PREFETCH_ENABLED or PREFETCH_COUNT <= 0:
            return
        existing = self._prefetch_tasks.get(chat_id)
        if existing and not existing.done():
            return
        task = asyncio.create_task(self._prefetch(chat_id), name=f"miko-prefetch-{chat_id}")
        self._prefetch_tasks[chat_id] = task
        task.add_done_callback(lambda _: self._prefetch_tasks.pop(chat_id, None))

    async def _prefetch(self, chat_id: int) -> None:
        from noxy import YouTube
        queue = list(db.get(chat_id) or [])
        if len(queue) < 2:
            return
        if await get_playmode(chat_id) != "Direct":
            return

        for entry in queue[1 : 1 + PREFETCH_COUNT]:
            if entry.source != "vid":
                continue
            try:
                await YouTube.download(entry.vidid, video=entry.is_video, videoid=True)
                LOGGER.debug("Prefetched %s for chat %s", entry.vidid, chat_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.debug("Prefetch failed for %s", entry.vidid, exc_info=True)
                return

    async def _autoplay_fill(self, chat_id: int) -> None:
        if not await get_autoplay(chat_id):
            return
        queue = db.get(chat_id) or []
        if len(queue) > 1:
            return
        if not queue:
            return

        current = queue[0]
        title = current.title.strip()
        if not title or current.streamtype not in {"audio", "video"}:
            return

        from noxy import YouTube

        history = self._autoplay_history.setdefault(chat_id, [])
        current_id = current.vidid
        if current_id and current_id not in history:
            history.append(current_id)
            del history[:-30]

        try:
            candidates = await YouTube.search_multi(
                f"{title} similar songs",
                limit=12,
                video=current.is_video,
                mode="performance",
            )
        except Exception:
            LOGGER.exception("Autoplay lookup failed for chat %s", chat_id)
            return

        track = next(
            (
                candidate
                for candidate in candidates
                if candidate
                and candidate.id
                and str(candidate.id) not in history
                and str(candidate.id) != current_id
                and 0 < candidate.duration_sec <= 900
            ),
            None,
        )
        if not track:
            return

        async with self.lock(chat_id):
            live_queue = db.get(chat_id) or []
            if len(live_queue) != 1 or live_queue[0].vidid != current_id:
                return
            live_queue.append(
                QueueItem(
                    title=track.title,
                    dur=track.duration,
                    streamtype=current.get("streamtype", "audio"),
                    by="Autoplay",
                    user_id=0,
                    chat_id=int(current.get("chat_id", chat_id)),
                    file=f"vid_{track.id}",
                    vidid=str(track.id),
                    seconds=max(0, track.duration_sec - 3),
                    autoplay=True,
                )
            )
            history.append(str(track.id))
            del history[:-30]
        LOGGER.info("Autoplay queued %r for chat %s", track.title, chat_id)

    async def _auto_leave_loop(self) -> None:
        while True:
            await asyncio.sleep(20)
            if not AUTO_LEAVING_ASSISTANT:
                continue
            now = asyncio.get_running_loop().time()
            for chat_id in list(await get_active_chats()):
                try:
                    client = await self.assistant(chat_id)
                    participants = await client.get_participants(chat_id)
                    if len(participants) > 1:
                        self._autoend.pop(chat_id, None)
                        continue

                    deadline = self._autoend.setdefault(chat_id, now + 60)
                    if now < deadline:
                        continue

                    async with self.lock(chat_id):
                        participants = await client.get_participants(chat_id)
                        if len(participants) > 1:
                            self._autoend.pop(chat_id, None)
                            continue
                        with contextlib.suppress(Exception):
                            await client.leave_call(chat_id)
                        await self._clear(chat_id)
                        LOGGER.info("Left idle voice chat %s", chat_id)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    LOGGER.debug("Auto-leave check failed for %s", chat_id, exc_info=True)
