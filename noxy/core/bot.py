from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.enums import ParseMode

from noxy.config import API_HASH, API_ID, BOT_TOKEN

LOGGER = logging.getLogger(__name__)


class MikoBot(Client):
    def __init__(self, name: str = "noximusic") -> None:
        super().__init__(
            name=name,
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            in_memory=True,
            parse_mode=ParseMode.HTML,
            sleep_threshold=0,
            max_concurrent_transmissions=16,
            max_message_cache_size=2000,
            no_updates=False,
            workers=64,
        )
        self.id: int = 0
        self.first_name: str = ""
        self.username: str = ""
        self.mention: str = ""

    async def start(self) -> MikoBot:
        await super().start()
        me = self.me
        self.id = me.id
        self.first_name = me.first_name
        self.username = me.username or ""
        self.mention = me.mention
        LOGGER.info(
            "Bot online: %s [ID: %s]",
            f"@{self.username}" if self.username else self.mention,
            self.id,
        )
        return self

    async def stop(self, *args, **kwargs):
        from pyrogram.errors import RPCError

        try:
            await super().stop(*args, **kwargs)
        except (RPCError, ConnectionError):
            LOGGER.debug("Bot client was not connected; nothing to stop.")
        else:
            LOGGER.info("Bot client disconnected.")
