from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass

from pyrogram import filters
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, LinkPreviewOptions, Message

from noxy import app
from noxy.config import SUPPORT_CHAT
from noxy.core.i18n import get_locale, get_text
from noxy.helpers.keyboards import (
    HELP_ORIGINS,
    help_menu_markup,
    help_section_markup,
    private_help_panel,
)

LOGGER = logging.getLogger(__name__)

PREVIEW_OFF = LinkPreviewOptions(is_disabled=True)


@dataclass(frozen=True, slots=True)
class _HelpTarget:
    section: str
    origin: str

    @property
    def from_start(self) -> bool:
        return self.origin == "start"


def _help_intro(from_start: bool) -> str:
    key = "help.start_intro" if from_start else "help.private_intro"
    return get_text(key, support=SUPPORT_CHAT)


def _parse_help_target(data: str | None) -> _HelpTarget | None:
    parts = (data or "").split(maxsplit=1)
    if len(parts) != 2:
        return None
    section, _, origin = parts[1].partition("|")
    if not section:
        return None
    return _HelpTarget(section=section, origin=origin if origin in HELP_ORIGINS else "help")


def _parse_origin(data: str | None) -> str:
    parts = (data or "").split(maxsplit=1)
    origin = parts[1].strip() if len(parts) == 2 else "help"
    return origin if origin in HELP_ORIGINS else "help"


def _section_text(section: str) -> str | None:
    value = get_locale(f"help.sections.{section}")
    return value if isinstance(value, str) else None


def _unavailable() -> str:
    return get_text("help.unavailable")


@app.on_message(filters.command(["help"]) & filters.private)
async def helper_private(client, message: Message):
    with contextlib.suppress(Exception):
        await message.delete()

    await message.reply_text(
        _help_intro(False),
        reply_markup=help_menu_markup(False),
        link_preview_options=PREVIEW_OFF,
    )


@app.on_callback_query(filters.regex(r"^help_menu(?:\s|$)"))
async def help_menu_callback(_, query: CallbackQuery):
    origin = _parse_origin(query.data)
    await query.answer()
    try:
        await query.edit_message_text(
            _help_intro(origin == "start"),
            reply_markup=help_menu_markup(origin == "start"),
            link_preview_options=PREVIEW_OFF,
        )
    except MessageNotModified:
        return


@app.on_message(filters.command(["help"]) & filters.group)
async def help_com_group(client, message: Message):
    await message.reply_text(
        get_text("help.group_intro"),
        reply_markup=private_help_panel(),
    )


@app.on_callback_query(filters.regex(r"^help_callback(?:\s|$)"))
async def helper_cb(client, query: CallbackQuery):
    target = _parse_help_target(query.data)
    if target is None:
        return await query.answer()

    text = _section_text(target.section)
    if text is None:
        return await query.answer(_unavailable(), show_alert=True)

    await query.answer()
    with contextlib.suppress(MessageNotModified):
        await query.edit_message_text(
            text,
            reply_markup=help_section_markup(target.section, target.origin),
            link_preview_options=PREVIEW_OFF,
        )
