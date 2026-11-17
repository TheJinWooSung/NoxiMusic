from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from pyrogram import filters
from pyrogram.enums import ChatType
from pyrogram.types import CallbackQuery, LinkPreviewOptions, Message

from noxy import _boot_, app, config, userbot
from noxy.core.i18n import get_text
from noxy.database import add_served_chat, add_served_user
from noxy.helpers.formatting import get_readable_time
from noxy.helpers.keyboards import (
    about_markup,
    help_menu_markup,
    private_panel,
    start_panel,
    track_info_markup,
)

LOGGER = logging.getLogger(__name__)

PREVIEW_OFF = LinkPreviewOptions(is_disabled=True)


@dataclass(frozen=True, slots=True)
class _TrackPreview:
    title: str
    duration: str
    views: str
    published: str
    channel: str
    channel_link: str
    url: str


def _uptime() -> str:
    return get_readable_time(int(time.time() - _boot_))


def _assistant_count() -> int:
    try:
        return len(userbot.started)
    except Exception:
        return 0


def _greeting_text(user: str) -> str:
    return get_text(
        "start.private_greeting",
        user=user,
        bot=app.mention,
        commands=get_text("ui.buttons.help"),
        support=config.SUPPORT_CHAT,
    )


def _group_text() -> str:
    return get_text(
        "start.group_greeting",
        bot=app.mention,
        uptime=_uptime(),
        support=config.SUPPORT_CHAT,
        channel=config.SUPPORT_CHANNEL,
        assistants=_assistant_count(),
    )


def _about_text() -> str:
    return get_text(
        "start.about_title",
        bot=app.mention,
        support=config.SUPPORT_CHAT,
        channel=config.SUPPORT_CHANNEL,
        uptime=_uptime(),
    )


async def _send_home(message: Message) -> None:
    await message.reply_text(
        text=_greeting_text(message.from_user.mention),
        reply_markup=private_panel(),
        link_preview_options=PREVIEW_OFF,
    )


async def _edit_home(query: CallbackQuery) -> None:
    await query.edit_message_text(
        text=_greeting_text(query.from_user.mention),
        reply_markup=private_panel(),
        link_preview_options=PREVIEW_OFF,
    )


def _parse_track_preview(result: dict, fallback_url: str) -> _TrackPreview:
    unknown = get_text("start.unknown")
    channel = result.get("channel") or {}
    views = result.get("viewCount") or {}
    return _TrackPreview(
        title=str(result.get("title") or unknown),
        duration=str(result.get("duration") or unknown),
        views=str(views.get("short") or unknown),
        published=str(result.get("publishedTime") or unknown),
        channel=str(channel.get("name") or unknown),
        channel_link=str(channel.get("link") or config.SUPPORT_CHAT),
        url=str(result.get("link") or fallback_url),
    )


async def _lookup_track(video_id: str) -> _TrackPreview | None:
    from py_yt import VideosSearch

    query = f"https://www.youtube.com/watch?v={video_id}"
    search = VideosSearch(query, limit=1)
    results = (await search.next()).get("result") or []
    if not results:
        return None
    return _parse_track_preview(results[0], query)


async def _send_track_info(message: Message, video_id: str) -> None:
    loading = await message.reply_text(get_text("start.track_loading"))
    try:
        preview = await _lookup_track(video_id) if video_id else None
    except Exception:
        LOGGER.debug("Track preview lookup failed for %s", video_id, exc_info=True)
        preview = None
    finally:
        await loading.delete()

    if preview is None:
        return await _send_home(message)

    await app.send_message(
        chat_id=message.chat.id,
        text=get_text(
            "start.track_info",
            title=preview.title,
            duration=preview.duration,
            views=preview.views,
            published=preview.published,
            channel=preview.channel,
            channel_link=preview.channel_link,
        ),
        reply_markup=track_info_markup(preview.url),
        link_preview_options=PREVIEW_OFF,
    )


@app.on_message(filters.command(["start"]) & filters.private)
async def start_pm(client, message: Message):
    await add_served_user(message.from_user.id)
    parts = (message.text or "").split(None, 1)
    payload = parts[1].strip() if len(parts) > 1 else ""

    if payload.startswith("help"):
        return await message.reply_text(
            text=get_text("start.help_link", support=config.SUPPORT_CHAT),
            reply_markup=help_menu_markup(True),
            link_preview_options=PREVIEW_OFF,
        )

    if payload.startswith("info_"):
        return await _send_track_info(message, payload.removeprefix("info_"))

    if payload.startswith("play_"):
        await message.reply_text(get_text("start.play_hint", bot=app.mention))

    return await _send_home(message)


@app.on_callback_query(filters.regex("^about_miko$"))
async def about_miko(_, query: CallbackQuery):
    await query.answer()
    in_group = query.message is not None and query.message.chat.type != ChatType.PRIVATE
    await query.edit_message_text(
        _about_text(),
        reply_markup=about_markup(in_group),
        link_preview_options=PREVIEW_OFF,
    )


@app.on_callback_query(filters.regex("^start_home$"))
async def start_home(_, query: CallbackQuery):
    await query.answer()
    await _edit_home(query)


@app.on_callback_query(filters.regex("^group_home$"))
async def group_home(_, query: CallbackQuery):
    await query.answer()
    await query.edit_message_text(
        _group_text(),
        reply_markup=start_panel(),
        link_preview_options=PREVIEW_OFF,
    )


@app.on_message(filters.command(["start"]) & filters.group)
async def start_gp(client, message: Message):
    await add_served_chat(message.chat.id)
    await message.reply_text(
        text=_group_text(),
        reply_markup=start_panel(),
        link_preview_options=PREVIEW_OFF,
    )


@app.on_message(filters.new_chat_members, group=-1)
async def welcome(client, message: Message):
    for member in message.new_chat_members:
        if member.id != app.id:
            continue
        try:
            if message.chat.type != ChatType.SUPERGROUP:
                await message.reply_text(get_text("start.need_supergroup"))
                await app.leave_chat(message.chat.id)
                return

            await message.reply_text(
                text=get_text(
                    "start.added_to_group",
                    user=message.from_user.first_name,
                    bot=app.mention,
                    chat=message.chat.title,
                    support=config.SUPPORT_CHAT,
                ),
                reply_markup=start_panel(),
                link_preview_options=PREVIEW_OFF,
            )
            await add_served_chat(message.chat.id)
            await message.stop_propagation()
        except Exception:
            LOGGER.exception("Failed to send the group welcome message")
