from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from html import escape
from typing import Any

from pyrogram import filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import CallbackQuery, Message

from noxy import app, db
from noxy.core.i18n import get_text
from noxy.database import is_active_chat, is_music_playing
from noxy.helpers.formatting import seconds_to_min
from noxy.helpers.keyboards import queue_back_markup, queue_markup
from noxy.helpers.pastebin import paste

LOGGER = logging.getLogger(__name__)

REFRESH_INTERVAL = 5

_basic: dict[tuple[int, str], bool] = {}


def _duration_known(playing: Sequence[dict[str, Any]]) -> bool:
    if not playing:
        return False
    file_ref = str(playing[0].get("file") or "")
    if "index_" in file_ref or "live_" in file_ref:
        return False
    return int(playing[0].get("seconds") or 0) > 0


def _player_caption(playing: Sequence[dict[str, Any]]) -> str:
    current = playing[0]
    known = _duration_known(playing)
    footer = get_text("queue.view_queue") if known else get_text("queue.duration_unknown")
    return get_text("queue.player").format(
        bot=app.mention,
        title=escape(str(current.get("title") or "Unknown Title").title()),
        stream_type=escape(str(current.get("streamtype") or "audio").title()),
        user=escape(str(current.get("by") or "Unknown")),
        footer=footer,
    )


def _player_keyboard(playing: Sequence[dict[str, Any]]) -> Any:
    current = playing[0]
    if not _duration_known(playing):
        return queue_markup(str(current.get("vidid") or ""))
    seconds = max(1, int(current.get("seconds") or 1))
    played = max(0, min(int(current.get("played") or 0), seconds))
    return queue_markup(
        str(current.get("vidid") or ""),
        played=seconds_to_min(played),
        total=str(current.get("dur") or "-"),
        progress=played / seconds,
    )


async def _auto_refresh(chat_id: int, videoid: str, message: Message) -> None:
    key = (chat_id, videoid)
    try:
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)
            playing = db.get(chat_id) or []
            if not playing or str(playing[0].get("vidid")) != videoid:
                return
            if not await is_active_chat(chat_id) or not _basic.get(key, False):
                return
            if not await is_music_playing(chat_id):
                continue
            try:
                await message.edit_reply_markup(reply_markup=_player_keyboard(playing))
            except FloodWait as exc:
                await asyncio.sleep(float(exc.value))
            except (MessageNotModified, ValueError):
                continue
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.debug("Stopped refreshing the player card in %s", chat_id, exc_info=True)
    finally:
        _basic.pop(key, None)


def _start_refresh(chat_id: int, videoid: str, message: Message) -> None:
    task = asyncio.create_task(
        _auto_refresh(chat_id, videoid, message), name=f"miko-queue-{chat_id}"
    )
    task.add_done_callback(lambda _: None)


@app.on_message(filters.command(["queue", "player", "playing"]) & filters.group)
async def get_queue(client, message: Message):
    chat_id = message.chat.id
    if not await is_active_chat(chat_id):
        return await message.reply_text(get_text("queue.not_streaming"))
    playing = db.get(chat_id) or []
    if not playing:
        return await message.reply_text(get_text("queue.nothing_playing"))

    videoid = str(playing[0].get("vidid") or "")
    _basic[(chat_id, videoid)] = True
    card = await message.reply_text(
        text=_player_caption(playing), reply_markup=_player_keyboard(playing)
    )
    if _duration_known(playing):
        _start_refresh(chat_id, videoid, card)


@app.on_callback_query(filters.regex("GetTimer"))
async def quite_timer(client, callback_query: CallbackQuery):
    with contextlib.suppress(Exception):
        await callback_query.answer()


@app.on_callback_query(filters.regex("GetQueued"))
async def queued_tracks(client, callback_query: CallbackQuery):
    data = (callback_query.data or "").strip()
    parts = data.split(None, 1)
    videoid = parts[1] if len(parts) == 2 else ""
    chat_id = callback_query.message.chat.id

    if not await is_active_chat(chat_id):
        return await callback_query.answer(get_text("queue.not_streaming_vc"), show_alert=True)
    playing = db.get(chat_id) or []
    if not playing:
        return await callback_query.answer(get_text("queue.nothing_playing"), show_alert=True)
    if len(playing) == 1:
        return await callback_query.answer(get_text("queue.only_one"), show_alert=True)

    await callback_query.answer()
    _basic[(chat_id, videoid)] = False
    buttons = queue_back_markup()
    await callback_query.edit_message_text(text=get_text("queue.fetching"))

    lines = []
    for index, entry in enumerate(playing, start=1):
        key = "streaming" if index == 1 else "queued" if index == 2 else "track"
        lines.append(
            get_text(
                f"queue.{key}",
                title=escape(f"{index}. {entry.get('title') or 'Unknown Title'!s}"),
                duration=escape(str(entry.get("dur") or "Unknown")),
                user=escape(str(entry.get("by") or "Unknown")),
            )
        )
    listing = "".join(lines) + get_text("queue.total", count=len(playing))

    if len(listing) <= 700:
        await asyncio.sleep(1)
        return await callback_query.edit_message_text(listing, reply_markup=buttons)

    with contextlib.suppress(Exception):
        link = await paste(listing)
        return await callback_query.edit_message_text(
            text=get_text("queue.paste_link", url=link), reply_markup=buttons
        )
    return await callback_query.edit_message_text(
        listing[:3900], reply_markup=buttons
    )


@app.on_callback_query(filters.regex("queue_back_timer"))
async def queue_back(client, callback_query: CallbackQuery):
    chat_id = callback_query.message.chat.id
    if not await is_active_chat(chat_id):
        return await callback_query.answer(get_text("queue.not_streaming_here"), show_alert=True)
    playing = db.get(chat_id) or []
    if not playing:
        return await callback_query.answer(get_text("queue.nothing_playing"), show_alert=True)

    videoid = str(playing[0].get("vidid") or "")
    _basic[(chat_id, videoid)] = True
    card = await callback_query.edit_message_text(
        text=_player_caption(playing), reply_markup=_player_keyboard(playing)
    )
    if _duration_known(playing):
        _start_refresh(chat_id, videoid, card)
