from __future__ import annotations

from pyrogram import filters
from pyrogram.types import Message

from noxy import app
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.database import set_loop
from noxy.helpers.decorators import AdminRightsCheck
from noxy.helpers.keyboards import close_markup


@app.on_message(filters.command(["end", "stop", "cend", "cstop"]) & filters.group)
@AdminRightsCheck
async def stop_music(cli, message: Message, chat_id):
    if len(message.command) != 1:
        return
    await noxy.stop_stream(chat_id)
    await set_loop(chat_id, 0)
    await message.reply_text(
        get_text("stop.stopped_by", user=message.from_user.mention),
        reply_markup=close_markup(),
    )
