from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Any

from noxy.database.cache import HotCache, WriteThroughCache, spawn_background
from noxy.database.mongo import (
    assdb,
    authdb,
    autoplaydb,
    chatsdb,
    languagesdb,
    playmodedb,
    playtypedb,
    usersdb,
)

LOGGER = logging.getLogger(__name__)

SUPPORTED_LANGUAGES = frozenset(
    {"en", "ar", "de", "es", "fa", "fr", "hi", "id", "it", "pt", "ru", "tr", "uz"}
)

active_chats: WriteThroughCache[int] = WriteThroughCache()
active_video_chats: WriteThroughCache[int] = WriteThroughCache()
assistant_map: HotCache[int, int] = HotCache(max_entries=10_000)
loop_map: HotCache[int, int] = HotCache(max_entries=10_000)
nonadmin_map: HotCache[int, bool] = HotCache(max_entries=10_000)
paused_map: HotCache[int, bool] = HotCache(max_entries=10_000)
playmode_map: HotCache[int, str] = HotCache(max_entries=10_000)
playtype_map: HotCache[int, str] = HotCache(max_entries=10_000)
autoplay_map: HotCache[int, bool] = HotCache(max_entries=10_000)

DEFAULT_PLAYTYPE = "Everyone"
DEFAULT_PLAYMODE = "Direct"
PROTECTED_CHAT = "protected"


@dataclass(frozen=True, slots=True)
class ChatAccess:
    playmode: str = DEFAULT_PLAYMODE
    playtype: str = DEFAULT_PLAYTYPE
    nonadmin: bool = False
    loop: int = 0
    autoplay: bool = False
    assistant: int | None = None
    playing: bool = False

    @property
    def direct(self) -> bool:
        return self.playmode == "Direct"

    @property
    def admin_commands(self) -> bool:
        return not self.nonadmin

    @property
    def admin_playback(self) -> bool:
        return self.playtype != "Everyone"


async def get_chat_access(chat_id: int) -> ChatAccess:
    return ChatAccess(
        playmode=await get_playmode(chat_id),
        playtype=await get_playtype(chat_id),
        nonadmin=await is_nonadmin_chat(chat_id),
        loop=await get_loop(chat_id),
        autoplay=await get_autoplay(chat_id),
        assistant=assistant_map.get(chat_id),
        playing=await is_active_chat(chat_id) and bool(paused_map.get(chat_id, False)),
    )


async def is_nonadmin_chat(chat_id: int) -> bool:
    mode = nonadmin_map.get(chat_id)
    if mode is not None:
        return mode
    record = await authdb.find_one({"chat_id": chat_id}, {"_id": 1})
    nonadmin_map.set(chat_id, record is not None)
    return record is not None


async def add_nonadmin_chat(chat_id: int) -> None:
    nonadmin_map.set(chat_id, True)
    await authdb.update_one(
        {"chat_id": chat_id}, {"$setOnInsert": {"chat_id": chat_id}}, upsert=True
    )


async def remove_nonadmin_chat(chat_id: int) -> None:
    nonadmin_map.set(chat_id, False)
    await authdb.delete_one({"chat_id": chat_id})


def _call_for(assistant: int | None):
    if assistant is None:
        return None
    from noxy.core.call import call

    return call.for_slot(int(assistant))


async def get_client(assistant: int):
    from noxy.core.assistants import assistants

    for number, client in assistants.items():
        if int(number) == int(assistant):
            return client
    return None


async def _available_assistants() -> list[int]:
    from noxy.core.assistants import assistants

    return sorted(assistants.keys())


async def set_assistant(chat_id: int, number: int | None = None):
    available = await _available_assistants()
    if not available:
        raise RuntimeError("No assistant session is configured.")
    chosen = int(number) if number is not None else random.choice(available)
    assistant_map.set(chat_id, chosen)
    await assdb.update_one(
        {"chat_id": chat_id}, {"$set": {"assistant": chosen}}, upsert=True
    )
    return await get_client(chosen)


async def get_assistant(chat_id: int):
    cached = assistant_map.get(chat_id)
    available = await _available_assistants()

    if cached is not None and cached in available:
        client = await get_client(cached)
        if client is not None:
            return client

    record = await assdb.find_one({"chat_id": chat_id}, {"assistant": 1})
    stored = record.get("assistant") if record else None
    if stored in available:
        assistant_map.set(chat_id, int(stored))
        client = await get_client(int(stored))
        if client is not None:
            return client

    return await set_assistant(chat_id)


async def group_assistant(number: int, chat_id: int):
    cached = assistant_map.get(chat_id)
    available = await _available_assistants()

    if cached is not None and cached in available:
        call_client = _call_for(cached)
        if call_client is not None:
            return call_client

    record = await assdb.find_one({"chat_id": chat_id}, {"assistant": 1})
    stored = record.get("assistant") if record else None
    if stored in available:
        assistant_map.set(chat_id, int(stored))
        call_client = _call_for(int(stored))
        if call_client is not None:
            return call_client

    await set_assistant(chat_id)
    chosen = assistant_map.get(chat_id)
    call_client = _call_for(chosen)
    if call_client is not None:
        return call_client

    call_slots = [slot for slot in available if _call_for(slot) is not None]
    if not call_slots:
        raise RuntimeError("No started PyTgCalls client is available.")

    chosen = random.choice(call_slots)
    assistant_map.set(chat_id, chosen)
    await assdb.update_one(
        {"chat_id": chat_id}, {"$set": {"assistant": chosen}}, upsert=True
    )
    return _call_for(chosen)


async def get_loop(chat_id: int) -> int:
    return int(loop_map.get(chat_id, 0) or 0)


async def set_loop(chat_id: int, mode: int) -> None:
    loop_map.set(chat_id, int(mode))


async def get_playtype(chat_id: int) -> str:
    mode = playtype_map.get(chat_id)
    if mode:
        return mode
    record = await playtypedb.find_one({"chat_id": chat_id}, {"mode": 1})
    mode = (record or {}).get("mode") or DEFAULT_PLAYTYPE
    playtype_map.set(chat_id, mode)
    return mode


async def set_playtype(chat_id: int, mode: str) -> None:
    playtype_map.set(chat_id, mode)
    await playtypedb.update_one(
        {"chat_id": chat_id}, {"$set": {"mode": mode}}, upsert=True
    )


async def get_playmode(chat_id: int) -> str:
    mode = playmode_map.get(chat_id)
    if mode:
        return mode
    record = await playmodedb.find_one({"chat_id": chat_id}, {"mode": 1})
    mode = (record or {}).get("mode") or DEFAULT_PLAYMODE
    playmode_map.set(chat_id, mode)
    return mode


async def set_playmode(chat_id: int, mode: str) -> None:
    playmode_map.set(chat_id, mode)
    await playmodedb.update_one(
        {"chat_id": chat_id}, {"$set": {"mode": mode}}, upsert=True
    )


async def is_music_playing(chat_id: int) -> bool:
    return bool(paused_map.get(chat_id, False))


async def music_on(chat_id: int) -> None:
    paused_map.set(chat_id, True)


async def music_off(chat_id: int) -> None:
    paused_map.set(chat_id, False)


async def get_active_chats() -> list[int]:
    return active_chats.snapshot()


async def is_active_chat(chat_id: int) -> bool:
    return chat_id in active_chats


async def add_active_chat(chat_id: int) -> None:
    if active_chats.add(chat_id):
        LOGGER.debug("Chat %s marked active.", chat_id)


async def remove_active_chat(chat_id: int) -> None:
    active_chats.discard(chat_id)
    paused_map.pop(chat_id, None)


async def get_active_video_chats() -> list[int]:
    return active_video_chats.snapshot()


async def is_active_video_chat(chat_id: int) -> bool:
    return chat_id in active_video_chats


async def add_active_video_chat(chat_id: int) -> None:
    active_video_chats.add(chat_id)


async def remove_active_video_chat(chat_id: int) -> None:
    active_video_chats.discard(chat_id)


async def is_served_user(user_id: int) -> bool:
    return await usersdb.find_one({"user_id": user_id}, {"_id": 1}) is not None


async def get_served_users() -> list[dict[str, Any]]:
    return [doc async for doc in usersdb.find({"user_id": {"$gt": 0}})]


async def add_served_user(user_id: int) -> None:
    await usersdb.update_one(
        {"user_id": user_id}, {"$setOnInsert": {"user_id": user_id}}, upsert=True
    )


async def get_served_chats() -> list[dict[str, Any]]:
    return [doc async for doc in chatsdb.find({"chat_id": {"$lt": 0}})]


async def is_served_chat(chat_id: int) -> bool:
    return await chatsdb.find_one({"chat_id": chat_id}, {"_id": 1}) is not None


async def add_served_chat(chat_id: int) -> None:
    await chatsdb.update_one(
        {"chat_id": chat_id}, {"$setOnInsert": {"chat_id": chat_id}}, upsert=True
    )


async def get_user_language(user_id: int) -> str:
    record = await languagesdb.find_one({"user_id": user_id}, {"language": 1})
    language = (record or {}).get("language")
    return language if language in SUPPORTED_LANGUAGES else "en"


async def set_user_language(user_id: int, language: str) -> bool:
    if language not in SUPPORTED_LANGUAGES:
        return False
    await languagesdb.update_one(
        {"user_id": user_id}, {"$set": {"language": language}}, upsert=True
    )
    return True


async def get_autoplay(chat_id: int) -> bool:
    enabled = autoplay_map.get(chat_id)
    if enabled is not None:
        return enabled
    record = await autoplaydb.find_one({"chat_id": chat_id}, {"enabled": 1})
    enabled = bool((record or {}).get("enabled", False))
    autoplay_map.set(chat_id, enabled)
    return enabled


async def set_autoplay(chat_id: int, enabled: bool) -> None:
    autoplay_map.set(chat_id, bool(enabled))
    if enabled:
        await autoplaydb.update_one(
            {"chat_id": chat_id}, {"$set": {"enabled": True}}, upsert=True
        )
    else:
        await autoplaydb.delete_one({"chat_id": chat_id})


def schedule(coro, *, name: str | None = None) -> None:
    spawn_background(coro, name=name)
