from __future__ import annotations

from pyrogram import filters

from noxy import app
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.core.state import adminlist
from noxy.database import (
    is_active_chat,
    is_music_playing,
    is_nonadmin_chat,
    music_off,
    music_on,
)
from noxy.helpers.keyboards import close_markup


@app.on_callback_query(filters.regex(r"^ADMIN(?:\s|$)"))
async def admin_playback_callback(client, query):
    parts = (query.data or "").strip().split(None, 1)
    if len(parts) != 2:
        return await query.answer(get_text("callback.manage_voice_chat"), show_alert=True)

    try:
        command, raw_chat_id = parts[1].split("|", 1)
        chat_id = int(raw_chat_id)
    except (ValueError, TypeError):
        return await query.answer(get_text("callback.manage_voice_chat"), show_alert=True)

    if command not in {"Pause", "Resume"} or not query.message or query.message.chat.id != chat_id:
        return await query.answer(get_text("callback.manage_voice_chat"), show_alert=True)

    if not await is_active_chat(chat_id):
        return await query.answer(get_text("callback.not_streaming"), show_alert=True)

    is_non_admin = await is_nonadmin_chat(chat_id)
    if not is_non_admin:
        admins = adminlist.get(chat_id)
        if not admins:
            return await query.answer(get_text("callback.reload_admins"), show_alert=True)
        if query.from_user.id not in admins:
            return await query.answer(get_text("callback.manage_voice_chat"), show_alert=True)

    mention = query.from_user.mention
    if command == "Pause":
        if not await is_music_playing(chat_id):
            return await query.answer(get_text("callback.already_paused"), show_alert=True)
        await query.answer()
        await music_off(chat_id)
        await noxy.pause_stream(chat_id)
        return await query.message.reply_text(
            get_text("callback.paused_by", user=mention),
            reply_markup=close_markup(),
        )

    if await is_music_playing(chat_id):
        return await query.answer(get_text("callback.already_resumed"), show_alert=True)
    await query.answer()
    await music_on(chat_id)
    await noxy.resume_stream(chat_id)
    return await query.message.reply_text(
        get_text("callback.resumed_by", user=mention),
        reply_markup=close_markup(),
    )
