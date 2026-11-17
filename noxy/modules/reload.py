from __future__ import annotations

import contextlib
import time

from pyrogram import filters
from pyrogram.enums import ChatMembersFilter, ChatMemberStatus
from pyrogram.types import CallbackQuery, Message

from noxy import app, db
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.core.state import adminlist, lyrical
from noxy.database import get_assistant
from noxy.helpers.decorators import ActualAdminCB, AdminActual
from noxy.helpers.formatting import get_readable_time

rel: dict[int, float] = {}
RELOAD_COOLDOWN = 180


@app.on_message(filters.command(["admincache", "reload", "refresh"]) & filters.group)
async def reload_admin_cache(client, message: Message):
    chat_id = message.chat.id
    saved = rel.get(chat_id, 0)
    if saved > time.time():
        left = get_readable_time(int(saved - time.time()))
        return await message.reply_text(get_text("reload.cooldown", time=left))

    try:
        admins = [
            member.user.id
            async for member in app.get_chat_members(
                chat_id, filter=ChatMembersFilter.ADMINISTRATORS
            )
            if member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
        ]
    except Exception:
        return await message.reply_text(get_text("reload.admin_error"))

    adminlist[chat_id] = admins
    rel[chat_id] = time.time() + RELOAD_COOLDOWN
    await message.reply_text(get_text("reload.admin_success"))


@app.on_message(filters.command(["reboot"]) & filters.group)
@AdminActual
async def restartbot(client, message: Message):
    mystic = await message.reply_text(get_text("reload.wait"))
    chat_id = message.chat.id

    with contextlib.suppress(Exception):
        db[chat_id] = []
        await noxy.stop_stream_force(chat_id)

    with contextlib.suppress(Exception):
        assistant = await get_assistant(chat_id)
        await assistant.resolve_peer(chat_id)

    await mystic.edit_text(get_text("reload.reboot_done"))


@app.on_callback_query(filters.regex("^close$"))
async def close_menu(_, callback_query: CallbackQuery):
    with contextlib.suppress(Exception):
        await callback_query.answer()
    with contextlib.suppress(Exception):
        await callback_query.message.delete()
    with contextlib.suppress(Exception):
        await callback_query.message.reply_text(
            get_text("reload.closed_by", user=callback_query.from_user.mention)
        )


@app.on_callback_query(filters.regex("^stop_downloading$"))
@ActualAdminCB
async def stop_download(client, callback_query: CallbackQuery):
    message_id = callback_query.message.id
    task = lyrical.get(message_id)
    if not task or task.done() or task.cancelled():
        return await callback_query.answer(get_text("reload.download_finished"), show_alert=True)

    task.cancel()
    lyrical.pop(message_id, None)
    await callback_query.answer(
        get_text("reload.download_cancelled"), show_alert=True
    )
    with contextlib.suppress(Exception):
        await callback_query.edit_message_text(
            get_text("reload.download_cancelled_by", user=callback_query.from_user.mention)
        )
