from __future__ import annotations

from pyrogram import filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, Message

from noxy import app
from noxy.core.i18n import get_text
from noxy.database import get_autoplay, set_autoplay
from noxy.helpers.decorators import ActualAdminCB, AdminRightsCheck
from noxy.helpers.keyboards import autoplay_markup


@app.on_message(filters.command(["autoplay"]) & filters.group)
@AdminRightsCheck
async def autoplay_command(_, message: Message, chat_id: int):
    args = message.command[1:] if len(message.command) > 1 else []
    if args:
        value = args[0].casefold()
        if value not in {"on", "off", "enable", "disable"}:
            return await message.reply_text(get_text("autoplay.usage"))
        enabled = value in {"on", "enable"}
        await set_autoplay(chat_id, enabled)
    else:
        enabled = await get_autoplay(chat_id)

    status = get_text("autoplay.enabled" if enabled else "autoplay.disabled")
    await message.reply_text(
        get_text("autoplay.panel", status=status),
        reply_markup=autoplay_markup(enabled),
    )


@app.on_callback_query(filters.regex(r"^AUTOPLAY:(ON|OFF)$"))
@ActualAdminCB
async def autoplay_callback(_, query: CallbackQuery):
    enabled = query.matches[0].group(1) == "ON"
    chat_id = query.message.chat.id
    await set_autoplay(chat_id, enabled)
    status = get_text("autoplay.enabled" if enabled else "autoplay.disabled")
    await query.answer(get_text("autoplay.updated", status=status).replace("<b>", "").replace("</b>", ""))
    try:
        await query.edit_message_text(
            get_text("autoplay.panel", status=status),
            reply_markup=autoplay_markup(enabled),
        )
    except MessageNotModified:
        return
