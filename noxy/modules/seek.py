from __future__ import annotations

import logging

from pyrogram import filters
from pyrogram.types import Message

from noxy import YouTube, app, db
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.helpers.decorators import AdminRightsCheck
from noxy.helpers.formatting import seconds_to_min
from noxy.helpers.keyboards import close_markup
from noxy.services.track import QueueItem

LOGGER = logging.getLogger(__name__)

MIN_REMAINING_SECONDS = 10


def _resolve_target(track: QueueItem) -> str:
    if track.speed_path:
        return track.speed_path
    if track.source == "index":
        return track.vidid
    return track.file


@app.on_message(filters.command(["seek", "cseek", "seekback", "cseekback"]) & filters.group)
@AdminRightsCheck
async def seek_comm(cli, message: Message, chat_id):
    if len(message.command) < 2:
        return await message.reply_text(get_text("seek.usage"))

    query = (message.text or "").split(None, 1)[1].strip()
    if not query.isdecimal():
        return await message.reply_text(get_text("seek.numeric"))

    playing = db.get(chat_id) or []
    if not playing:
        return await message.reply_text(get_text("seek.empty_queue"))

    track = playing[0]
    if track.seconds == 0:
        return await message.reply_text(get_text("seek.live_not_supported"))

    offset = int(query)
    backwards = "back" in message.command[0].lower()
    known = seconds_to_min(track.played)

    if backwards:
        if track.played - offset <= MIN_REMAINING_SECONDS:
            return await _too_far(message, known, track.dur)
        target = track.played - offset + 1
    else:
        if track.seconds - (track.played + offset) <= MIN_REMAINING_SECONDS:
            return await _too_far(message, known, track.dur)
        target = track.played + offset + 1

    progress = await message.reply_text(get_text("seek.seeking"))
    if track.source == "vid":
        status, refreshed = await YouTube.video(track.vidid)
        if status == 0 or not refreshed:
            return await progress.edit_text(get_text("seek.live_not_supported"))
        file_path = refreshed
    else:
        file_path = _resolve_target(track)

    try:
        await noxy.seek_stream(
            chat_id,
            file_path,
            seconds_to_min(target),
            track.dur,
            track.streamtype,
        )
    except Exception:
        LOGGER.exception("Failed to seek stream in chat %s", chat_id)
        return await progress.edit_text(get_text("seek.failed"), reply_markup=close_markup())

    live = db.get(chat_id) or []
    if live:
        live[0].played = max(0, live[0].played + (-offset if backwards else offset))

    return await progress.edit_text(
        get_text(
            "seek.success",
            position=seconds_to_min(target),
            user=message.from_user.mention,
        ),
        reply_markup=close_markup(),
    )


async def _too_far(message: Message, played: str, duration: str) -> None:
    await message.reply_text(
        get_text("seek.too_far", played=played, duration=duration),
        reply_markup=close_markup(),
    )
