from __future__ import annotations

from collections.abc import Awaitable, Callable

from pyrogram import filters
from pyrogram.types import LinkPreviewOptions, Message
from unidecode import unidecode

from noxy import app
from noxy.config import OWNER_ID
from noxy.core.i18n import get_text
from noxy.database import (
    get_active_chats,
    get_active_video_chats,
    remove_active_chat,
    remove_active_video_chat,
)

PREVIEW_OFF = LinkPreviewOptions(is_disabled=True)


async def _active_report(
    chat_ids: list[int],
    remove_chat: Callable[[int], Awaitable[None]],
    empty_key: str,
) -> str:
    lines = []
    for chat_id in chat_ids:
        try:
            chat = await app.get_chat(chat_id)
        except Exception:
            await remove_chat(chat_id)
            continue

        title = unidecode(chat.title or get_text("start.unknown")).upper()
        username = chat.username
        if username:
            lines.append(
                get_text(
                    "active.chat_link",
                    index=len(lines) + 1,
                    title=title,
                    username=username,
                    chat_id=chat_id,
                )
            )
        else:
            lines.append(
                get_text(
                    "active.chat",
                    index=len(lines) + 1,
                    title=title,
                    chat_id=chat_id,
                )
            )

    if not lines:
        return get_text(empty_key, bot=app.mention)
    return get_text("active.header") + "\n\n" + "\n".join(lines)


async def _send_active(
    message: Message,
    chat_ids: list[int],
    remove_chat: Callable[[int], Awaitable[None]],
    empty_key: str,
) -> None:
    status = await message.reply_text(get_text("active.loading"))
    report = await _active_report(chat_ids, remove_chat, empty_key)
    await status.edit_text(report, link_preview_options=PREVIEW_OFF)


@app.on_message(filters.command(["activevc", "activevoice"]) & filters.user(OWNER_ID))
async def activevc(_, message: Message):
    return await _send_active(
        message, await get_active_chats(), remove_active_chat, "active.none_voice"
    )


@app.on_message(filters.command(["activev", "activevideo"]) & filters.user(OWNER_ID))
async def activevi_(_, message: Message):
    return await _send_active(
        message,
        await get_active_video_chats(),
        remove_active_video_chat,
        "active.none_video",
    )
