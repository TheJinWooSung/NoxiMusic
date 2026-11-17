from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from functools import wraps
from typing import Any

from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import (
    ChatAdminRequired,
    InviteRequestSent,
    UserAlreadyParticipant,
    UserNotParticipant,
)
from pyrogram.types import Message

from noxy import YouTube, app, db
from noxy.core.i18n import get_text
from noxy.core.limits import QUEUE_LIMIT
from noxy.core.state import adminlist
from noxy.database import get_assistant, get_chat_access, is_active_chat
from noxy.helpers.decorators import _anonymous_admin_markup
from noxy.helpers.keyboards import botplaylist_markup

INVITE_LINKS: dict[int, str] = {}
JOIN_SETTLE_SECONDS = 1.0
APPROVAL_SETTLE_SECONDS = 3.0


@dataclass(frozen=True, slots=True)
class PlayRequest:
    chat_id: int
    video: bool | None
    playmode: str
    url: str | None
    fplay: bool | None
    user_id: int

    @classmethod
    def build(cls, message: Message, playmode: str) -> PlayRequest:
        command = message.command or []
        name = command[0] if command else ""
        if name.startswith("v"):
            video: bool | None = True
        else:
            video = None
        return cls(
            chat_id=message.chat.id,
            video=video,
            playmode="Direct",
            url=None,
            fplay=True if name.endswith("e") else None,
            user_id=message.from_user.id if message.from_user else 0,
        )


def _invite_target(message: Message, chat_id: int) -> str | None:
    if chat_id in INVITE_LINKS:
        return INVITE_LINKS[chat_id]
    if message.chat.username:
        return message.chat.username
    return None


async def _invite_assistant(message: Message, chat_id: int, assistant: Any) -> bool:
    invite = _invite_target(message, chat_id)
    if invite is None:
        try:
            invite = await app.export_chat_invite_link(chat_id)
        except ChatAdminRequired:
            await message.reply_text(get_text("play_wrapper.assistant_invite_permission"))
            return False
        except Exception as exc:
            await message.reply_text(
                get_text(
                    "play_wrapper.assistant_invite_failed",
                    bot=app.mention,
                    reason=type(exc).__name__,
                )
            )
            return False

    if invite.startswith("https://t.me/+"):
        invite = invite.replace("https://t.me/+", "https://t.me/joinchat/")
    INVITE_LINKS[chat_id] = invite

    status = await message.reply_text(get_text("play_wrapper.wait"))
    try:
        await assistant.join_chat(invite)
        await asyncio.sleep(JOIN_SETTLE_SECONDS)
    except InviteRequestSent:
        try:
            await app.approve_chat_join_request(chat_id, assistant.id)
        except Exception as exc:
            await message.reply_text(
                get_text(
                    "play_wrapper.assistant_invite_failed",
                    bot=app.mention,
                    reason=type(exc).__name__,
                )
            )
            return False
        await asyncio.sleep(APPROVAL_SETTLE_SECONDS)
        await message.reply_text(get_text("play_wrapper.try_again"))
        with contextlib.suppress(Exception):
            await status.delete()
    except UserAlreadyParticipant:
        pass
    except Exception as exc:
        await message.reply_text(
            get_text(
                "play_wrapper.assistant_invite_failed",
                bot=app.mention,
                reason=type(exc).__name__,
            )
        )
        return False

    with contextlib.suppress(Exception):
        await assistant.resolve_peer(chat_id)
    return True


async def _ensure_assistant(message: Message, chat_id: int) -> bool:
    if await is_active_chat(chat_id):
        return True

    assistant = await get_assistant(chat_id)
    try:
        member = await app.get_chat_member(chat_id, assistant.id)
    except ChatAdminRequired:
        await message.reply_text(get_text("play_wrapper.assistant_invite_permission"))
        return False
    except UserNotParticipant:
        return await _invite_assistant(message, chat_id, assistant)
    except Exception:
        return False

    if member.status in (ChatMemberStatus.BANNED, ChatMemberStatus.RESTRICTED):
        await message.reply_text(
            get_text("play_wrapper.assistant_banned").format(
                app.mention, assistant.id, assistant.name, assistant.username
            )
        )
        return False
    return True


async def _check_usage(message: Message) -> bool:
    has_media = bool(
        message.reply_to_message
        and (
            message.reply_to_message.audio
            or message.reply_to_message.voice
            or message.reply_to_message.video
            or message.reply_to_message.document
        )
    )
    if has_media or await YouTube.url(message):
        return True
    if len(message.command) >= 2:
        return True
    if "stream" in (message.command or []):
        await message.reply_text(get_text("play_wrapper.m3u8_required"))
        return False
    await message.reply_text(
        text=get_text("play_wrapper.usage"),
        reply_markup=botplaylist_markup(),
    )
    return False


async def _authorised(message: Message, access: Any) -> bool:
    if not access.admin_playback:
        return True
    admins = adminlist.get(message.chat.id)
    if not admins:
        await message.reply_text(get_text("play_wrapper.admin_cache"))
        return False
    if not message.from_user or message.from_user.id not in admins:
        await message.reply_text(get_text("play_wrapper.admins_only"))
        return False
    return True


def PlayWrapper(command):
    @wraps(command)
    async def wrapper(client, message: Message):
        if message.sender_chat:
            return await message.reply_text(
                get_text("play_wrapper.anonymous_admin"),
                reply_markup=_anonymous_admin_markup(),
            )

        chat_id = message.chat.id
        if await is_active_chat(chat_id) and len(db.get(chat_id, [])) >= QUEUE_LIMIT:
            return await message.reply_text(
                get_text("play_wrapper.queue_limit", limit=QUEUE_LIMIT)
            )

        with contextlib.suppress(Exception):
            await message.delete()

        if not await _check_usage(message):
            return None

        access = await get_chat_access(chat_id)
        if not await _authorised(message, access):
            return None

        request = PlayRequest.build(message, access.playmode)
        if request.fplay and not await is_active_chat(chat_id):
            return await message.reply_text(get_text("play_wrapper.voice_chat_required"))
        if not await _ensure_assistant(message, chat_id):
            return None

        url = await YouTube.url(message)
        return await command(
            client,
            message,
            chat_id,
            request.video,
            request.playmode,
            url,
            request.fplay,
        )

    return wrapper
