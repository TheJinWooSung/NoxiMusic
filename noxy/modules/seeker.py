from __future__ import annotations

import asyncio
import logging

from noxy import db
from noxy.database import get_active_chats, is_music_playing

LOGGER = logging.getLogger(__name__)

TICK_SECONDS = 1.0
RETRY_SECONDS = 5.0

_playback_timer: asyncio.Task | None = None


async def tick() -> None:
    try:
        active_chats = await get_active_chats()
    except Exception:
        LOGGER.debug("Failed to retrieve active music chats", exc_info=True)
        return

    for chat_id in active_chats:
        try:
            if not await is_music_playing(chat_id):
                continue
            playing = db.get(chat_id)
            if not playing:
                continue
            current = playing[0]
            if current.seconds <= 0 or current.played >= current.seconds:
                continue
            current.played += 1
        except (AttributeError, IndexError, TypeError, ValueError):
            LOGGER.warning("Skipping invalid playback state for chat %s", chat_id)
        except Exception:
            LOGGER.exception("Playback timer failed for chat %s", chat_id)


async def timer() -> None:
    loop = asyncio.get_running_loop()
    next_tick = loop.time()
    while True:
        now = loop.time()
        if now - next_tick > TICK_SECONDS:
            next_tick = now
        next_tick += TICK_SECONDS
        await asyncio.sleep(max(0.0, next_tick - now))
        try:
            await tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Playback timer tick failed")
            await asyncio.sleep(RETRY_SECONDS)


def start_background_tasks() -> None:
    global _playback_timer
    if _playback_timer is None or _playback_timer.done():
        _playback_timer = asyncio.create_task(timer(), name="noximusic-playback-timer")
