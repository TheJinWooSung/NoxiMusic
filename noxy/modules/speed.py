from __future__ import annotations

from pyrogram import filters
from pyrogram.types import Message

from noxy import app, db
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.core.state import adminlist
from noxy.database import is_active_chat, is_nonadmin_chat
from noxy.helpers.decorators import AdminRightsCheck
from noxy.helpers.keyboards import close_markup, speed_markup

checker: set[int] = set()


@app.on_message(filters.command(["speed", "slow", "playback"]) & filters.group)
@AdminRightsCheck
async def playback(cli, message: Message, chat_id):
    playing = db.get(chat_id)
    if not playing:
        return await message.reply_text(get_text("speed.empty_queue"))
    duration_seconds = int(playing[0].get("seconds", 0))
    if duration_seconds == 0 or "downloads" not in str(playing[0].get("file", "")):
        return await message.reply_text(get_text("speed.unsupported"))
    return await message.reply_text(
        text=get_text("speed.choose"),
        reply_markup=speed_markup(chat_id),
    )


@app.on_callback_query(filters.regex(r"^SpeedUP(?:\s|$)"))
async def change_speed(client, query):
    parts = query.data.strip().split(None, 1)
    if len(parts) != 2:
        return await query.answer(get_text("speed.invalid_request"), show_alert=True)

    try:
        chat, speed = parts[1].split("|", 1)
        chat_id = int(chat)
        speed_value = float(speed)
    except (ValueError, TypeError):
        return await query.answer(get_text("speed.invalid_request"), show_alert=True)

    if not query.message or query.message.chat.id != chat_id:
        return await query.answer(get_text("speed.invalid_request"), show_alert=True)
    if speed_value not in {0.5, 0.75, 1.0, 1.5, 2.0}:
        return await query.answer(get_text("speed.invalid_request"), show_alert=True)
    if not await is_active_chat(chat_id):
        return await query.answer(get_text("speed.not_streaming"), show_alert=True)

    non_admin_mode = await is_nonadmin_chat(chat_id)
    if not non_admin_mode:
        admins = adminlist.get(chat_id)
        if not admins:
            return await query.answer(get_text("speed.reload_admins"), show_alert=True)
        if query.from_user.id not in admins:
            return await query.answer(get_text("speed.no_permission"), show_alert=True)

    playing = db.get(chat_id)
    if not playing:
        return await query.answer(get_text("speed.empty_queue"), show_alert=True)
    track = playing[0]
    if int(track.get("seconds", 0)) == 0 or "downloads" not in str(track.get("file", "")):
        return await query.answer(get_text("speed.unsupported"), show_alert=True)

    current_speed = float(track.get("speed") or 1.0)
    if current_speed == speed_value:
        return await query.answer(
            get_text("speed.already_normal") if speed_value == 1.0 else get_text("speed.already_set", speed=speed_value),
            show_alert=True,
        )
    if chat_id in checker:
        return await query.answer(get_text("speed.busy"), show_alert=True)

    checker.add(chat_id)
    status = None
    try:
        await query.answer(get_text("speed.changing"))
        status = await query.edit_message_text(
            get_text("speed.requested", user=query.from_user.mention)
        )
        await noxy.speedup_stream(chat_id, track["file"], str(speed_value), playing)
        await status.edit_text(
            get_text("speed.changed", speed=speed_value, user=query.from_user.mention),
            reply_markup=close_markup(),
        )
    except Exception:
        try:
            if status:
                await status.edit_text(get_text("speed.failed"), reply_markup=close_markup())
            else:
                await query.answer(get_text("speed.failed"), show_alert=True)
        except Exception:
            pass
    finally:
        checker.discard(chat_id)
