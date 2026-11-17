import contextlib
from functools import wraps

from pyrogram.enums import ChatMemberStatus, ChatType
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from noxy import app
from noxy.core.i18n import get_text
from noxy.core.state import adminlist
from noxy.database import is_active_chat, is_nonadmin_chat


def _anonymous_admin_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text=get_text("admin.anonymous_button"),
            callback_data="AnonymousAdmin",
        )]]
    )


async def _can_manage_voice_chat(chat_id: int, user_id: int) -> bool:
    try:
        member = await app.get_chat_member(chat_id, user_id)
    except Exception:
        return False

    if member.status == ChatMemberStatus.OWNER:
        return True

    privileges = member.privileges
    return bool(
        member.status == ChatMemberStatus.ADMINISTRATOR
        and privileges
        and privileges.can_manage_video_chats
    )


def AdminRightsCheck(mystic):
    @wraps(mystic)
    async def wrapper(client, message):
        with contextlib.suppress(Exception):
            await message.delete()

        if message.sender_chat:
            return await message.reply_text(
                get_text("admin.anonymous_admin"),
                reply_markup=_anonymous_admin_markup(),
            )

        chat_id = message.chat.id
        if not await is_active_chat(chat_id):
            return await message.reply_text(get_text("admin.not_streaming"))

        if not await is_nonadmin_chat(chat_id):
            admins = adminlist.get(chat_id)
            if not admins:
                return await message.reply_text(get_text("admin.refresh_cache"))
            if not message.from_user or message.from_user.id not in admins:
                return await message.reply_text(get_text("admin.no_manage_rights"))

        return await mystic(client, message, chat_id)

    return wrapper


def AdminActual(mystic):
    @wraps(mystic)
    async def wrapper(client, message):
        with contextlib.suppress(Exception):
            await message.delete()

        if message.sender_chat:
            return await message.reply_text(
                get_text("admin.anonymous_admin"),
                reply_markup=_anonymous_admin_markup(),
            )

        if not message.from_user or not await _can_manage_voice_chat(
            message.chat.id, message.from_user.id
        ):
            return await message.reply_text(get_text("admin.actual_no_rights"))

        return await mystic(client, message)

    return wrapper


def ActualAdminCB(mystic):
    @wraps(mystic)
    async def wrapper(client, callback_query):
        message = callback_query.message
        if message.chat.type == ChatType.PRIVATE:
            return await mystic(client, callback_query)

        if await is_nonadmin_chat(message.chat.id):
            return await mystic(client, callback_query)

        if not await _can_manage_voice_chat(
            message.chat.id, callback_query.from_user.id
        ):
            return await callback_query.answer(
                get_text("admin.callback_no_rights"),
                show_alert=True,
            )

        return await mystic(client, callback_query)

    return wrapper
