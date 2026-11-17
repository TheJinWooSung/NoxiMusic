from __future__ import annotations

import asyncio
import contextlib
import logging

from pyrogram.types import InputMediaPhoto, LinkPreviewOptions
from pytgcalls import PyTgCalls

from noxy import config, db
from noxy.core.i18n import get_text
from noxy.database import add_active_video_chat, get_loop, set_loop
from noxy.helpers.cleanup import auto_clean
from noxy.helpers.keyboards import stream_markup
from noxy.helpers.thumbnail import DEFAULT_THUMB, get_thumb
from noxy.services.track import QueueItem

from .streams import Unplayable, stream_for

LOGGER = logging.getLogger(__name__)


class CallPlaybackMixin:
    async def play(self, client: PyTgCalls | None, chat_id: int) -> None:
        async with self.lock(chat_id):
            await self._play_locked(client, chat_id)

    async def _play_locked(self, client: PyTgCalls | None, chat_id: int) -> None:
        queue = db.get(chat_id) or []
        if client is None:
            client = await self.assistant(chat_id)

        loop_count = await get_loop(chat_id)
        try:
            if loop_count == 0:
                finished = queue.pop(0) if queue else None
                if finished:
                    await auto_clean(finished)
            else:
                await set_loop(chat_id, loop_count - 1)
                finished = None
            if not queue:
                await self._clear(chat_id)
                with contextlib.suppress(Exception):
                    await client.leave_call(chat_id)
                return
        except Exception:
            LOGGER.debug("Queue drain failed for chat %s", chat_id, exc_info=True)
            await self._clear(chat_id)
            with contextlib.suppress(Exception):
                await client.leave_call(chat_id)
            return

        entry = queue[0]
        entry.played = 0
        entry.reset_speed()

        playing_video = entry.is_video
        try:
            markup = await self._start_track(client, chat_id, entry)
        except Unplayable:
            return await self._recover(client, chat_id, entry.chat_id or chat_id)
        except Exception:
            LOGGER.exception("Could not start the next track in chat %s", chat_id)
            return await self._recover(client, chat_id, entry.chat_id or chat_id)
        self._consecutive_failures.pop(chat_id, None)

        if playing_video:
            await add_active_video_chat(chat_id)

        await self._post_card(chat_id, entry, markup)
        self._schedule_prefetch(chat_id)

    async def _start_track(self, client: PyTgCalls, chat_id: int, entry: QueueItem) -> str:
        if entry.source == "live":
            from noxy import YouTube

            ok, link = await YouTube.video(entry.vidid)
            if not ok or not link:
                raise Unplayable(entry.vidid)
            await client.play(chat_id, stream_for(link, video=entry.is_video))
            return "tg"

        if entry.source == "vid":
            from noxy import YouTube

            path, _ = await YouTube.download(entry.vidid, video=entry.is_video, videoid=True)
            if not path:
                raise Unplayable(entry.vidid)
            await client.play(chat_id, stream_for(path, video=entry.is_video))
            return "stream"

        target = entry.vidid if entry.source == "index" else entry.file
        await client.play(chat_id, stream_for(target, video=entry.is_video))
        return "tg"

    async def _post_card(self, chat_id: int, entry: QueueItem, markup: str) -> None:
        username = self._bot().username or ""
        info_url = (
            f"https://t.me/{username}?start=info_{entry.vidid}"
            if entry.vidid and username
            else config.SUPPORT_CHAT
        )
        caption = get_text("skip.started_streaming").format(
            url=info_url,
            title=entry.title[:30],
            duration=entry.dur or "00:00",
            user=entry.by,
        )
        target_chat = entry.chat_id or chat_id
        try:
            placeholder = await get_thumb(
                "",
                title=entry.title,
                duration=entry.dur or "00:00",
                username=username,
            )
            run = await self._bot().send_photo(
                chat_id=target_chat,
                photo=placeholder,
                caption=caption,
                reply_markup=stream_markup(chat_id),
            )
        except Exception:
            LOGGER.warning(
                "Could not post the instant player card in chat %s; using text fallback",
                chat_id,
                exc_info=True,
            )
            try:
                run = await self._bot().send_message(
                    chat_id=target_chat,
                    text=caption,
                    reply_markup=stream_markup(chat_id),
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
            except Exception:
                LOGGER.debug("Could not post the now-playing card", exc_info=True)
                return

        entry.mystic = run
        entry.markup = markup
        task = asyncio.create_task(
            self._refresh_player_thumbnail(
                run, target_chat, chat_id, entry, caption, username
            ),
            name=f"miko-thumbnail-{chat_id}",
        )
        task.add_done_callback(
            lambda completed: completed.exception()
            if not completed.cancelled() and completed.exception()
            else None
        )

    async def _refresh_player_thumbnail(
        self,
        message,
        target_chat: int,
        chat_id: int,
        entry: QueueItem,
        caption: str,
        username: str,
    ) -> None:
        try:
            thumbnail = await get_thumb(
                entry.vidid,
                title=entry.title,
                duration=entry.dur or "00:00",
                username=username,
            )
            if not thumbnail or thumbnail == DEFAULT_THUMB:
                return
            await self._bot().edit_message_media(
                chat_id=target_chat,
                message_id=message.id,
                media=InputMediaPhoto(media=thumbnail, caption=caption),
                reply_markup=stream_markup(chat_id),
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.debug(
                "Could not refresh player thumbnail for chat %s",
                chat_id,
                exc_info=True,
            )

    async def _recover(self, client: PyTgCalls, chat_id: int, original_chat_id: int) -> None:
        failures = self._consecutive_failures.get(chat_id, 0) + 1
        self._consecutive_failures[chat_id] = failures
        LOGGER.warning("Skipping unplayable track in chat %s (failures=%s)", chat_id, failures)

        with contextlib.suppress(Exception):
            await self._bot().send_message(original_chat_id, get_text("playback.failed_track_skipping"))

        if failures >= 5:
            LOGGER.error("Giving up on chat %s after %s consecutive failures", chat_id, failures)
            self._consecutive_failures.pop(chat_id, None)
            await self._clear(chat_id)
            with contextlib.suppress(Exception):
                await client.leave_call(chat_id)
            return

        await set_loop(chat_id, 0)
        await self._play_locked(client, chat_id)
