from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass
from typing import Any

from pyrogram import filters
from pyrogram.types import LinkPreviewOptions, Message

from noxy import YouTube, app, config, db
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.database import get_loop
from noxy.helpers.cleanup import auto_clean
from noxy.helpers.decorators import AdminRightsCheck
from noxy.helpers.keyboards import close_markup, stream_markup

LOGGER = logging.getLogger(__name__)

PREVIEW_OFF = LinkPreviewOptions(is_disabled=True)
MAX_BULK_SKIP = 1


@dataclass(frozen=True, slots=True)
class _Skipped:
    title: str
    file: str
    vidid: str
    user: str
    duration: str
    streamtype: str

    @property
    def is_video(self) -> bool:
        return str(self.streamtype) == "video"

    @property
    def source_kind(self) -> str:
        for marker in ("live_", "vid_", "index_"):
            if marker in self.file:
                return marker.rstrip("_")
        return "file"


def _skipped_entry(entry: dict[str, Any]) -> _Skipped:
    return _Skipped(
        title=str(entry.get("title") or "").title(),
        file=str(entry.get("file") or ""),
        vidid=str(entry.get("vidid") or ""),
        user=str(entry.get("by") or ""),
        duration=str(entry.get("dur") or ""),
        streamtype=str(entry.get("streamtype") or ""),
    )


def _reset_speed_state(entry: dict[str, Any]) -> None:
    original = entry.get("old_dur")
    if not original:
        return
    entry["dur"] = original
    entry["seconds"] = entry.get("old_second", entry.get("seconds", 0))
    entry["speed_path"] = None
    entry["speed"] = 1.0


async def _switch(chat_id: int, track: _Skipped, mystic: Message | None) -> str | None:
    if track.source_kind == "live":
        status, link = await YouTube.video(track.vidid)
        if status == 0:
            return None
        await noxy.skip_stream(chat_id, link, video=track.is_video)
        return link

    if track.source_kind == "index":
        await noxy.skip_stream(chat_id, track.vidid, video=track.is_video)
        return track.vidid

    if track.source_kind == "vid":
        if mystic is None:
            return None
        file_path, _ = await YouTube.download(
            track.vidid, mystic, videoid=True, video=track.is_video
        )
        if not file_path:
            return None
        await noxy.skip_stream(chat_id, file_path, video=track.is_video)
        return file_path

    await noxy.skip_stream(chat_id, track.file, video=track.is_video)
    return track.file


def _now_playing_text(track: _Skipped) -> str:
    if track.source_kind == "index":
        return get_text("skip.started_url_stream", user=track.user)
    if track.vidid in {"telegram", "soundcloud"}:
        url = config.SUPPORT_CHAT
    else:
        url = f"https://t.me/{app.username}?start=info_{track.vidid}"
    return get_text(
        "skip.started_streaming",
        url=url,
        title=track.title[:30],
        duration=track.duration,
        user=track.user,
    )


async def _post_now_playing(message: Message, chat_id: int, track: _Skipped) -> None:
    card = await message.reply_text(
        text=_now_playing_text(track),
        reply_markup=stream_markup(chat_id),
        link_preview_options=PREVIEW_OFF,
    )
    entry = db.get(chat_id)
    if entry:
        entry[0]["mystic"] = card
        entry[0]["markup"] = "stream" if track.source_kind == "vid" else "tg"


async def _bulk_skip(message: Message, chat_id: int, count: int) -> bool:
    queue = db.get(chat_id) or []
    for _ in range(count):
        if not queue:
            break
        popped = queue.pop(0)
        if popped:
            await auto_clean(popped)
    if queue:
        return False
    await message.reply_text(
        get_text(
            "skip.skipped_by",
            user=message.from_user.mention,
            chat=message.chat.title,
        ),
        reply_markup=close_markup(),
    )
    await noxy.stop_stream_force(chat_id)
    return True


@app.on_message(filters.command(["skip", "cskip", "next", "cnext"]) & filters.group)
@AdminRightsCheck
async def skip(cli, message: Message, chat_id):
    async with noxy.lock(chat_id):
        if len(message.command) < 2:
            return await _skip_current(message, chat_id)

        loop = await get_loop(chat_id)
        if loop != 0:
            return await message.reply_text(get_text("skip.disable_loop"))

        argument = message.text.split(None, 1)[1].strip()
        if not argument.isnumeric():
            return await message.reply_text(get_text("skip.invalid_number"))

        queue = db.get(chat_id) or []
        if not queue:
            return await message.reply_text(get_text("skip.empty_queue"))
        count = len(queue)
        if count <= 2:
            return await message.reply_text(get_text("skip.need_two"))

        requested = int(argument)
        available = count - 1
        if not 1 <= requested <= available:
            return await message.reply_text(get_text("skip.not_enough", count=available))

        if await _bulk_skip(message, chat_id, requested):
            return None
        return await _start_next(message, chat_id)


async def _start_next(
    message: Message,
    chat_id: int,
    *,
    remove_current: bool = False,
) -> None:
    queue = db.get(chat_id) or []
    index = 1 if remove_current else 0
    if len(queue) <= index:
        if remove_current and queue:
            finished = queue.pop(0)
            await auto_clean(finished)
        await noxy.stop_stream_force(chat_id)
        return await message.reply_text(
            get_text(
                "skip.skipped_by",
                user=message.from_user.mention,
                chat=message.chat.title,
            ),
            reply_markup=close_markup(),
        )

    entry = queue[index]
    track = _skipped_entry(entry)
    entry.played = 0
    _reset_speed_state(entry)

    mystic = None
    if track.source_kind == "vid":
        mystic = await message.reply_text(
            get_text("skip.downloading_next"), link_preview_options=PREVIEW_OFF
        )

    try:
        switched = await _switch(chat_id, track, mystic)
        if not switched:
            raise RuntimeError("The next track could not be prepared.")
    except Exception:
        LOGGER.exception("Failed to switch to the next track in %s", chat_id)
        target = mystic or message
        await target.edit_text(get_text("skip.switch_failed"))
        return

    if remove_current:
        finished = queue.pop(0)
        await auto_clean(finished)

    await _post_now_playing(message, chat_id, track)
    if mystic is not None:
        with contextlib.suppress(Exception):
            await mystic.delete()


async def _skip_current(message: Message, chat_id: int) -> None:
    await _start_next(message, chat_id, remove_current=True)
