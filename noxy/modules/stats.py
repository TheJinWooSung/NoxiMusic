from __future__ import annotations

import asyncio
import logging
import platform
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import psutil
from pyrogram import filters
from pyrogram.enums import ButtonStyle
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from noxy import app, config
from noxy.core.assistants import assistants
from noxy.core.i18n import get_text
from noxy.core.settings import AUTO_LEAVING_ASSISTANT
from noxy.database import chatsdb, mongodb, usersdb
from noxy.modules import ALL_MODULES

LOGGER = logging.getLogger(__name__)

PROCESS = psutil.Process()
SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def _package_version(*names: str) -> str:
    for name in names:
        try:
            return version(name)
        except PackageNotFoundError:
            continue
    return "unknown"


def _format_bytes(value: float) -> str:
    size = float(value)
    for unit in SIZE_UNITS:
        if size < 1024 or unit == SIZE_UNITS[-1]:
            return f"{size:.0f}{unit}" if unit == "B" else f"{size:.2f}{unit}"
        size /= 1024
    return f"{size:.2f}{SIZE_UNITS[-1]}"


async def _count_blocked(collection_names: list[str], *, users: bool) -> int:
    tokens = ("user", "users") if users else ("chat", "chats", "group")
    candidates = [
        name
        for name in collection_names
        if ("block" in name.lower() or "blacklist" in name.lower())
        and any(token in name.lower() for token in tokens)
    ]
    if not candidates:
        return 0

    counts = await asyncio.gather(
        *(mongodb[name].count_documents({}) for name in candidates),
        return_exceptions=True,
    )
    total = 0
    for name, result in zip(candidates, counts, strict=False):
        if isinstance(result, Exception):
            LOGGER.warning("Unable to count blocked entries in %s", name)
            continue
        total += int(result)
    return total


@dataclass(frozen=True, slots=True)
class StatsSnapshot:
    chats: int
    users: int
    blocked_chats: int
    blocked_users: int
    assistants: int
    modules: int
    cpu_percent: float
    cpu_cores: int
    memory_used: str
    memory_total: str
    disk_used: str
    disk_total: str
    system: str
    python: str
    pyrogram: str
    pytgcalls: str
    ntgcalls: str

    @classmethod
    async def collect(cls) -> StatsSnapshot:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.cwd()))
        collection_names = await mongodb.list_collection_names()
        chats, users, blocked_chats, blocked_users = await asyncio.gather(
            chatsdb.count_documents({"chat_id": {"$lt": 0}}),
            usersdb.count_documents({"user_id": {"$gt": 0}}),
            _count_blocked(collection_names, users=False),
            _count_blocked(collection_names, users=True),
        )
        return cls(
            chats=int(chats),
            users=int(users),
            blocked_chats=blocked_chats,
            blocked_users=blocked_users,
            assistants=len(assistants),
            modules=len(ALL_MODULES),
            cpu_percent=psutil.cpu_percent(interval=None),
            cpu_cores=psutil.cpu_count(logical=True) or 0,
            memory_used=_format_bytes(PROCESS.memory_info().rss),
            memory_total=_format_bytes(memory.total),
            disk_used=_format_bytes(disk.used),
            disk_total=_format_bytes(disk.total),
            system=platform.system(),
            python=platform.python_version(),
            pyrogram=_package_version("kurigram", "pyrogram"),
            pytgcalls=_package_version("py-tgcalls", "pytgcalls"),
            ntgcalls=_package_version("ntgcalls"),
        )

    def render(self, bot_name: str, auto_leave: bool) -> str:
        return (
            f"<b>❖ {bot_name} · Overview</b>\n\n"
            f"<blockquote><b>Chats served:</b> <code>{self.chats}</code>\n"
            f"<b>Users served:</b> <code>{self.users}</code>\n"
            f"<b>Blocked chats:</b> <code>{self.blocked_chats}</code>\n"
            f"<b>Blocked users:</b> <code>{self.blocked_users}</code></blockquote>\n\n"
            f"<blockquote><b>Assistants:</b> <code>{self.assistants}</code>\n"
            f"<b>Modules:</b> <code>{self.modules}</code>\n"
            f"<b>Auto leave:</b> <code>{auto_leave}</code></blockquote>\n\n"
            f"<b>Runtime</b>\n"
            f"<pre>{self.memory_used} / {self.memory_total} RAM | "
            f"{self.cpu_percent:.1f}% CPU ({self.cpu_cores} cores)\n"
            f"{self.disk_used} / {self.disk_total} disk | {self.system}</pre>\n\n"
            f"<pre>Python {self.python} | Kurigram {self.pyrogram}\n"
            f"PyTgCalls {self.pytgcalls} | NTgCalls {self.ntgcalls}</pre>"
        )


def _is_owner(user_id: int | None) -> bool:
    return bool(config.OWNER_ID and user_id == config.OWNER_ID)


def _refresh_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_text("ui.buttons.refresh"),
                    callback_data="stats_back",
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text=get_text("ui.buttons.close"),
                    callback_data="close",
                    style=ButtonStyle.DANGER,
                ),
            ]
        ]
    )


@app.on_message(filters.command(["stats", "gstats"]))
async def stats_global(_, message: Message):
    if not _is_owner(message.from_user.id if message.from_user else None):
        return await message.reply_text(get_text("stats.owner_only"))
    try:
        snapshot = await StatsSnapshot.collect()
    except Exception:
        LOGGER.exception("Unable to build bot statistics.")
        return await message.reply_text(get_text("stats.unavailable"))
    return await message.reply_text(
        snapshot.render(app.name or "NoxiMusic", AUTO_LEAVING_ASSISTANT),
        reply_markup=_refresh_markup(),
        disable_web_page_preview=True,
    )


@app.on_callback_query(filters.regex("^(stats_back|TopOverall)$"))
async def home_stats(_, query: CallbackQuery):
    if not _is_owner(query.from_user.id if query.from_user else None):
        return await query.answer(get_text("stats.owner_only"), show_alert=True)
    try:
        snapshot = await StatsSnapshot.collect()
    except Exception:
        LOGGER.exception("Unable to refresh bot statistics.")
        return await query.answer(get_text("stats.unavailable"), show_alert=True)
    await query.answer()
    return await query.edit_message_text(
        snapshot.render(app.name or "NoxiMusic", AUTO_LEAVING_ASSISTANT),
        reply_markup=_refresh_markup(),
        disable_web_page_preview=True,
    )
