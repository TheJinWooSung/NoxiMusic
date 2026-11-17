from __future__ import annotations

import logging
import time

import psutil
from pyrogram import filters
from pyrogram.types import Message

from noxy import app
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.database import group_assistant

LOGGER = logging.getLogger(__name__)
VOICE_CHAT_TYPES = frozenset({"group", "supergroup"})


@app.on_message(filters.command(["ping", "latency"]))
async def ping_command(_, message: Message) -> None:
    started = time.perf_counter()
    status = await message.reply_text(get_text("ping.checking"))
    bot_ms = (time.perf_counter() - started) * 1000

    call_ms = None
    try:
        chat_type = getattr(message.chat.type, "value", message.chat.type)
        assistant = (
            await group_assistant(noxy, message.chat.id)
            if chat_type in VOICE_CHAT_TYPES
            else noxy.for_slot(1)
        )
        if assistant is None:
            raise RuntimeError("No voice-call client is running.")
        call_ms = float(assistant.ping)
    except Exception:
        LOGGER.debug("Failed to measure PyTgCalls ping.", exc_info=True)

    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory().percent
    call_text = (
        get_text("ping.call_ms", milliseconds=f"{call_ms:.2f}")
        if call_ms is not None
        else get_text("ping.call_unavailable")
    )
    await status.edit_text(
        get_text(
            "ping.result",
            bot_ms=f"{bot_ms:.2f}",
            call_latency=call_text,
            cpu=f"{cpu:.1f}",
            memory=f"{memory:.1f}",
        )
    )
