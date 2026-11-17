from __future__ import annotations

from pyrogram import filters
from pyrogram.types import Message

from noxy import app
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.database import is_music_playing, music_on
from noxy.helpers.decorators import AdminRightsCheck
from noxy.helpers.keyboards import close_markup


@app.on_message(filters.command(["resume", "cresume"]) & filters.group)
@AdminRightsCheck
async def resume_com(cli, message: Message, chat_id):
    if await is_music_playing(chat_id):
        return await message.reply_text(get_text("playback.already_resumed"))
    await music_on(chat_id)
    await noxy.resume_stream(chat_id)
    await message.reply_text(
        get_text("playback.resumed_by", user=message.from_user.mention),
        reply_markup=close_markup(),
    )
