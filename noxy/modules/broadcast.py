from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from pyrogram import filters
from pyrogram.enums import ChatMembersFilter
from pyrogram.errors import FloodWait, RPCError

from noxy import app
from noxy.config import OWNER_ID
from noxy.core.i18n import get_text
from noxy.core.state import adminlist
from noxy.database import get_active_chats, get_client, get_served_chats, get_served_users

LOGGER = logging.getLogger(__name__)

SEND_DELAY = 0.2
ASSISTANT_DELAY = 3.0
MAX_FLOOD_WAIT = 200

FLAGS = frozenset({"-pin", "-nobot", "-pinloud", "-assistant", "-user"})

_broadcasting = False


@dataclass(slots=True, frozen=True)
class BroadcastJob:
    text: str
    source_chat: int | None = None
    source_message: int | None = None
    pin: bool = False
    loud: bool = False
    to_bot: bool = True
    to_users: bool = False
    to_assistants: bool = False

    @classmethod
    def parse(cls, message: Any) -> BroadcastJob | None:
        text = message.text or message.caption or ""
        tokens = text.split(None, 1)
        body = tokens[1] if len(tokens) > 1 else ""
        for flag in FLAGS:
            body = body.replace(flag, "")
        body = body.strip()

        reply = message.reply_to_message
        has_pin = "-pin" in text or "-pinloud" in text
        job = cls(
            text=body,
            source_chat=message.chat.id if reply else None,
            source_message=reply.id if reply else None,
            pin=has_pin,
            loud="-pinloud" in text,
            to_bot="-nobot" not in text,
            to_users="-user" in text,
            to_assistants="-assistant" in text,
        )
        if not reply and not body:
            return None
        return job

    @property
    def has_targets(self) -> bool:
        return self.to_bot or self.to_users or self.to_assistants


@dataclass(slots=True)
class DeliveryReport:
    sent: int = 0
    failed: int = 0
    pinned: int = 0

    def summary(self, label: str) -> str:
        return (
            f"<b>{label}</b>\n"
            + get_text("broadcast.delivered")
            + f": <code>{self.sent}</code>\n"
            + get_text("broadcast.failed")
            + f": <code>{self.failed}</code>\n"
            + get_text("broadcast.pinned")
            + f": <code>{self.pinned}</code>"
        )


async def _deliver(client: Any, chat_id: int, job: BroadcastJob, report: DeliveryReport) -> None:
    try:
        if job.source_message is not None and job.source_chat is not None:
            sent = await client.forward_messages(chat_id, job.source_chat, job.source_message)
        else:
            sent = await client.send_message(chat_id, text=job.text)
        report.sent += 1
        if job.pin and sent is not None:
            try:
                await sent.pin(disable_notification=not job.loud)
                report.pinned += 1
            except RPCError:
                LOGGER.debug("Could not pin broadcast in %s", chat_id)
    except FloodWait as exc:
        wait = int(getattr(exc, "value", 0) or 0)
        if 0 < wait <= MAX_FLOOD_WAIT:
            await asyncio.sleep(wait)
            await _deliver(client, chat_id, job, report)
            return
        report.failed += 1
    except Exception:
        report.failed += 1
        LOGGER.debug("Broadcast delivery failed for %s", chat_id, exc_info=True)


async def _broadcast(client: Any, targets: list[int], job: BroadcastJob, delay: float) -> DeliveryReport:
    report = DeliveryReport()
    for chat_id in targets:
        await _deliver(client, chat_id, job, report)
        await asyncio.sleep(delay)
    return report


@app.on_message(filters.command("broadcast") & filters.user(OWNER_ID))
async def broadcast_message(client, message):
    global _broadcasting
    if _broadcasting:
        return await message.reply_text(get_text("broadcast.busy"))

    job = BroadcastJob.parse(message)
    if job is None:
        return await message.reply_text(get_text("broadcast.usage"))

    _broadcasting = True
    try:
        await message.reply_text(get_text("broadcast.started"))
        reports: list[str] = []

        if job.to_bot:
            chats = [int(chat["chat_id"]) for chat in await get_served_chats()]
            reports.append(
                (await _broadcast(app, chats, job, SEND_DELAY)).summary(get_text("broadcast.chats"))
            )

        if job.to_users:
            users = [int(user["user_id"]) for user in await get_served_users()]
            reports.append(
                (await _broadcast(app, users, job, SEND_DELAY)).summary(get_text("broadcast.users"))
            )

        if job.to_assistants:
            from noxy.core.assistants import assistants

            for number in list(assistants):
                assistant = await get_client(number)
                if assistant is None:
                    continue
                dialogs = [dialog.chat.id async for dialog in assistant.get_dialogs()]
                report = await _broadcast(assistant, dialogs, job, ASSISTANT_DELAY)
                reports.append(report.summary(get_text("broadcast.assistant", number=number)))

        await message.reply_text(
            "\n\n".join(reports) if reports else get_text("broadcast.nothing")
        )
    finally:
        _broadcasting = False


async def _refresh_admin_cache() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            active = await get_active_chats()
        except Exception:
            LOGGER.debug("Could not list active chats for the admin cache", exc_info=True)
            continue

        for chat_id in active:
            if chat_id in adminlist:
                continue
            try:
                adminlist[chat_id] = [
                    member.user.id
                    async for member in app.get_chat_members(
                        chat_id, filter=ChatMembersFilter.ADMINISTRATORS
                    )
                    if member.privileges and member.privileges.can_manage_video_chats
                ]
            except Exception:
                LOGGER.debug("Could not refresh admins for %s", chat_id, exc_info=True)


_admin_refresh_task: asyncio.Task | None = None


def start_background_tasks() -> None:
    global _admin_refresh_task
    if _admin_refresh_task is None or _admin_refresh_task.done():
        _admin_refresh_task = asyncio.create_task(
            _refresh_admin_cache(), name="noximusic-admin-cache"
        )
