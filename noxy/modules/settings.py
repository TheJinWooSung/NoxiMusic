from __future__ import annotations

import contextlib

from pyrogram import filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from noxy import app
from noxy.core.i18n import get_languages, get_text, set_current_language
from noxy.database import (
    ChatAccess,
    add_nonadmin_chat,
    get_chat_access,
    get_playmode,
    get_playtype,
    get_user_language,
    is_nonadmin_chat,
    remove_nonadmin_chat,
    set_loop,
    set_playmode,
    set_playtype,
    set_user_language,
)
from noxy.helpers.decorators import ActualAdminCB, AdminRightsCheck
from noxy.helpers.keyboards import close_markup, language_markup, settings_markup

LOOP_RANGE = (1, 10)


def _panel_markup(access: ChatAccess, *, with_language: bool) -> InlineKeyboardMarkup:
    return settings_markup(
        direct=access.direct,
        admin_commands=access.admin_commands,
        admin_playback=access.admin_playback,
        with_language=with_language,
    )


async def _playmode_markup(chat_id: int, user_id: int | None = None) -> InlineKeyboardMarkup:
    return _panel_markup(await get_chat_access(chat_id), with_language=user_id is not None)


def _language_markup(current: str) -> InlineKeyboardMarkup:
    return language_markup(current, list(get_languages().items()))


@app.on_message(filters.command(["settings", "setting", "playmode", "mode"]) & filters.group)
async def settings_mar(_, message: Message):
    await message.reply_text(
        get_text(
            "ui.settings.panel",
            bot=app.mention,
            chat_id=message.chat.id,
            chat_title=message.chat.title,
        ),
        reply_markup=await _playmode_markup(message.chat.id, message.from_user.id),
    )


@app.on_callback_query(filters.regex("settings_helper"))
async def settings_cb(_, query: CallbackQuery):
    return await query.edit_message_reply_markup(
        reply_markup=await _playmode_markup(query.message.chat.id, query.from_user.id)
    )


@app.on_callback_query(
    filters.regex(pattern=r"^(SEARCHANSWER|PLAYMODEANSWER|PLAYTYPEANSWER|AUTHANSWER|PM)$")
)
async def settings_callbacks(_, query: CallbackQuery):
    command = query.matches[0].group(1)
    chat_id = query.message.chat.id
    if command in ("SEARCHANSWER", "PLAYMODEANSWER", "PLAYTYPEANSWER", "AUTHANSWER"):
        text = {
            "SEARCHANSWER": get_text("ui.settings.search_mode"),
            "PLAYMODEANSWER": get_text("ui.settings.play_mode"),
            "PLAYTYPEANSWER": get_text("ui.settings.play_type"),
            "AUTHANSWER": get_text("ui.settings.admin_commands"),
        }[command]
        return await query.answer(text, show_alert=True)
    if command == "PM":
        return await query.edit_message_reply_markup(reply_markup=await _playmode_markup(chat_id, query.from_user.id))


@app.on_callback_query(
    filters.regex(pattern=r"^(MODECHANGE|AUTHMODECHANGE|PLAYTYPECHANGE)$")
)
@ActualAdminCB
async def playmode_ans(_, query: CallbackQuery):
    chat_id = query.message.chat.id
    command = query.matches[0].group(1)
    if command == "AUTHMODECHANGE":
        if not await is_nonadmin_chat(chat_id):
            await add_nonadmin_chat(chat_id)
        else:
            await remove_nonadmin_chat(chat_id)
    elif command == "MODECHANGE":
        mode = "Inline" if await get_playmode(chat_id) == "Direct" else "Direct"
        await set_playmode(chat_id, mode)
    elif command == "PLAYTYPECHANGE":
        playtype = "Admin" if await get_playtype(chat_id) == "Everyone" else "Everyone"
        await set_playtype(chat_id, playtype)
    with contextlib.suppress(MessageNotModified):
        await query.edit_message_reply_markup(
            reply_markup=await _playmode_markup(chat_id, query.from_user.id)
        )


@app.on_message(filters.command(["loop", "cloop"]) & filters.group)
@AdminRightsCheck
async def configure_loop(_, message: Message, chat_id: int):
    usage = get_text("loop.usage")
    if len(message.command) != 2:
        return await message.reply_text(usage)

    value = message.command[1].strip().lower()
    if value in {"disable", "off", "0"}:
        await set_loop(chat_id, 0)
        return await message.reply_text(
            get_text("loop.disabled", user=message.from_user.mention),
            reply_markup=close_markup(),
        )

    low, high = LOOP_RANGE
    if value in {"enable", "on"}:
        repeats = high
    elif value.isdecimal() and low <= int(value) <= high:
        repeats = int(value)
    else:
        return await message.reply_text(usage)

    await set_loop(chat_id, repeats)
    return await message.reply_text(
        get_text("loop.enabled", count=repeats, user=message.from_user.mention),
        reply_markup=close_markup(),
    )


@app.on_callback_query(filters.regex(r"^LANGUAGESETTINGS$"))
async def language_settings(_, query: CallbackQuery):
    current = await get_user_language(query.from_user.id)
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=_language_markup(current))


@app.on_callback_query(filters.regex(r"^LANGSET:(en|ar|de|es|fa|fr|hi|id|it|pt|ru|tr|uz)$"))
async def language_set(_, query: CallbackQuery):
    language = query.matches[0].group(1)
    await set_user_language(query.from_user.id, language)
    set_current_language(language)
    await query.answer(get_text("ui.settings.language_saved", language=get_languages()[language]))
    if query.message and query.message.chat:
        await query.edit_message_reply_markup(reply_markup=_language_markup(language))


@app.on_callback_query(filters.regex(r"^LANGUAGEBACK$"))
async def language_back(_, query: CallbackQuery):
    await query.answer()
    await query.edit_message_reply_markup(
        reply_markup=await _playmode_markup(query.message.chat.id, query.from_user.id)
    )


@app.on_message(filters.all, group=-100)
async def apply_message_language(_, message: Message):
    if message.from_user:
        set_current_language(await get_user_language(message.from_user.id))


@app.on_callback_query(filters.all, group=-100)
async def apply_callback_language(_, query: CallbackQuery):
    set_current_language(await get_user_language(query.from_user.id))
