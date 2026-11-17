from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Final

from pyrogram.enums import ButtonStyle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from noxy import app, config
from noxy.core.i18n import get_locale, get_text

ButtonRows = list[list[InlineKeyboardButton]]

PRIMARY: Final[ButtonStyle] = ButtonStyle.PRIMARY
SUCCESS: Final[ButtonStyle] = ButtonStyle.SUCCESS
DANGER: Final[ButtonStyle] = ButtonStyle.DANGER

PLAY_GLYPH: Final[str] = "▷"
PAUSE_GLYPH: Final[str] = "❚❚"

HELP_ORIGINS: Final[frozenset[str]] = frozenset({"start", "help"})


def _label(key: str, **values: Any) -> str:
    return get_text(key, **values)


def _callback(text: str, data: str, style: ButtonStyle = PRIMARY) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data, style=style)


def _link(text: str, url: str, style: ButtonStyle = PRIMARY) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, url=url, style=style)


def _grid(buttons: Iterable[InlineKeyboardButton], per_row: int = 2) -> ButtonRows:
    items = list(buttons)
    width = max(1, int(per_row))
    return [items[index : index + width] for index in range(0, len(items), width)]


def _markup(*rows: Sequence[InlineKeyboardButton] | None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(row) for row in rows if row])


def _close_button() -> InlineKeyboardButton:
    return _callback(_label("ui.buttons.close"), "close", DANGER)


def _back_button(data: str) -> InlineKeyboardButton:
    return _callback(_label("ui.buttons.back"), data, DANGER)


def group_invite_url() -> str:
    username = app.username or ""
    return f"https://t.me/{username}?startgroup=true"


def help_topic_entries() -> list[tuple[str, str]]:
    topics = get_locale("help.menu")
    if not isinstance(topics, list):
        return []
    entries: list[tuple[str, str]] = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        label = topic.get("label")
        section = topic.get("section")
        if isinstance(label, str) and isinstance(section, str):
            entries.append((label, section))
    return entries


def help_section_order() -> list[str]:
    return [section for _, section in help_topic_entries()]


def close_markup() -> InlineKeyboardMarkup:
    return _markup([_close_button()])


def supp_markup() -> InlineKeyboardMarkup:
    return _markup([_link(_label("ui.buttons.support_group"), config.SUPPORT_CHAT)])


def botplaylist_markup() -> InlineKeyboardMarkup:
    return _markup(
        [
            _link(_label("ui.buttons.support_group"), config.SUPPORT_CHAT),
            _close_button(),
        ]
    )


def track_markup(videoid: str, user_id: int, fplay: str) -> InlineKeyboardMarkup:
    return _markup(
        [
            _callback(_label("ui.buttons.audio"), f"MusicStream {videoid}|{user_id}|a|{fplay}"),
            _callback(_label("ui.buttons.video"), f"MusicStream {videoid}|{user_id}|v|{fplay}"),
        ],
        [_callback(_label("ui.buttons.close"), f"forceclose {videoid}|{user_id}", DANGER)],
    )


def playlist_markup(videoid: str, user_id: int, ptype: str, fplay: str) -> InlineKeyboardMarkup:
    prefix = f"ShizukuPlaylists {videoid}|{user_id}|{ptype}"
    return _markup(
        [
            _callback(_label("ui.buttons.audio"), f"{prefix}|a|{fplay}"),
            _callback(_label("ui.buttons.video"), f"{prefix}|v|{fplay}"),
        ],
        [_callback(_label("ui.buttons.close"), f"forceclose {videoid}|{user_id}", DANGER)],
    )


def livestream_markup(videoid: str, user_id: int, mode: str, fplay: str) -> InlineKeyboardMarkup:
    return _markup(
        [
            _callback(
                _label("ui.buttons.live_stream"),
                f"LiveStream {videoid}|{user_id}|{mode}|{fplay}",
            )
        ],
        [_callback(_label("ui.buttons.close"), f"forceclose {videoid}|{user_id}", DANGER)],
    )


def slider_markup(
    videoid: str,
    user_id: int,
    query: str,
    query_type: int,
    fplay: str,
) -> InlineKeyboardMarkup:
    trimmed = query[:20]
    return _markup(
        [
            _callback(_label("ui.buttons.audio"), f"MusicStream {videoid}|{user_id}|a|{fplay}"),
            _callback(_label("ui.buttons.video"), f"MusicStream {videoid}|{user_id}|v|{fplay}"),
        ],
        [
            _callback("‹", f"slider B|{query_type}|{trimmed}|{user_id}|{fplay}"),
            _callback(_label("ui.buttons.close"), f"forceclose {trimmed}|{user_id}", DANGER),
            _callback("›", f"slider F|{query_type}|{trimmed}|{user_id}|{fplay}"),
        ],
    )


def stream_markup(chat_id: int) -> InlineKeyboardMarkup:
    return _markup(
        [
            _callback(PLAY_GLYPH, f"ADMIN Resume|{chat_id}", SUCCESS),
            _callback(PAUSE_GLYPH, f"ADMIN Pause|{chat_id}", DANGER),
        ],
        [_close_button()],
    )


def aq_markup(chat_id: int) -> InlineKeyboardMarkup:
    return _markup(
        [
            _callback(PLAY_GLYPH, f"ADMIN Resume|{chat_id}", SUCCESS),
            _callback(PAUSE_GLYPH, f"ADMIN Pause|{chat_id}", DANGER),
        ]
    )


def queue_markup(
    videoid: str,
    *,
    played: str | None = None,
    total: str | None = None,
    progress: float | None = None,
) -> InlineKeyboardMarkup:
    if not played or not total:
        return _markup(
            [
                _callback(_label("ui.buttons.queue"), f"GetQueued {videoid}"),
                _close_button(),
            ]
        )
    if progress is None:
        progress = 0.0
    progress = max(0.0, min(float(progress), 1.0))
    segments = 12
    filled = round(progress * (segments - 1))
    bar = "━" * filled + "●" + "─" * (segments - 1 - filled)
    return _markup(
        [_callback(f"{played}  {bar}  {total}", "GetTimer")],
        [
            _callback(_label("ui.buttons.queue"), f"GetQueued {videoid}"),
            _close_button(),
        ],
    )


def queue_back_markup() -> InlineKeyboardMarkup:
    return _markup([_back_button("queue_back_timer"), _close_button()])


def speed_markup(chat_id: int) -> InlineKeyboardMarkup:
    return _markup(
        [
            _callback("0.5×", f"SpeedUP {chat_id}|0.5"),
            _callback("0.75×", f"SpeedUP {chat_id}|0.75"),
        ],
        [_callback(_label("ui.buttons.normal"), f"SpeedUP {chat_id}|1.0", SUCCESS)],
        [
            _callback("1.5×", f"SpeedUP {chat_id}|1.5"),
            _callback("2.0×", f"SpeedUP {chat_id}|2.0"),
        ],
        [_close_button()],
    )


def start_panel() -> InlineKeyboardMarkup:
    return _markup(
        [
            _link(_label("ui.buttons.add_me"), group_invite_url(), SUCCESS),
            _link(_label("ui.buttons.support_group"), config.SUPPORT_CHAT),
        ],
        [
            _callback(_label("ui.buttons.about"), "about_miko"),
            _link(_label("ui.buttons.news_channel"), config.SUPPORT_CHANNEL),
        ],
    )


def private_panel() -> InlineKeyboardMarkup:
    return _markup(
        [
            _link(_label("ui.buttons.add_me"), group_invite_url(), SUCCESS),
            _callback(_label("ui.buttons.help"), "help_menu start"),
        ],
        [
            _callback(_label("ui.buttons.about"), "about_miko"),
            _link(_label("ui.buttons.support_group"), config.SUPPORT_CHAT),
        ],
        [_link(_label("ui.buttons.news_channel"), config.SUPPORT_CHANNEL)],
    )


def about_markup(in_group: bool = False) -> InlineKeyboardMarkup:
    return _markup(
        [
            _link(_label("ui.buttons.support_group"), config.SUPPORT_CHAT),
            _link(_label("ui.buttons.news_channel"), config.SUPPORT_CHANNEL),
        ],
        [_callback(_label("ui.buttons.back"), "group_home" if in_group else "start_home", DANGER)],
    )


def track_info_markup(url: str) -> InlineKeyboardMarkup:
    return _markup(
        [
            _link(_label("start.youtube_button"), url),
            _link(_label("ui.buttons.support_group"), config.SUPPORT_CHAT),
        ],
        [_callback(_label("ui.buttons.close"), "close", DANGER)],
    )


def help_menu_markup(from_start: bool = False) -> InlineKeyboardMarkup:
    origin = "start" if from_start else "help"
    buttons = [
        _callback(_label(f"ui.buttons.{label}"), f"help_callback {section}|{origin}")
        for label, section in help_topic_entries()
    ]
    rows = _grid(buttons)
    rows.append([_link(_label("ui.buttons.support_group"), config.SUPPORT_CHAT)])
    rows.append(
        [
            _callback(
                _label("ui.buttons.back") if from_start else _label("ui.buttons.close"),
                "start_home" if from_start else "close",
                DANGER,
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def help_section_markup(section: str, origin: str = "help") -> InlineKeyboardMarkup:
    resolved = origin if origin in HELP_ORIGINS else "help"
    order = help_section_order()
    navigation: list[InlineKeyboardButton] = []
    if section in order:
        position = order.index(section)
        if position > 0:
            previous = order[position - 1]
            navigation.append(
                _callback(_label("ui.buttons.prev"), f"help_callback {previous}|{resolved}")
            )
        if position + 1 < len(order):
            following = order[position + 1]
            navigation.append(
                _callback(_label("ui.buttons.next"), f"help_callback {following}|{resolved}")
            )
    return _markup(
        navigation,
        [
            _callback(_label("ui.buttons.topics"), f"help_menu {resolved}", DANGER),
            _close_button(),
        ],
    )


def private_help_panel() -> InlineKeyboardMarkup:
    return _markup(
        [_link(_label("ui.buttons.commands"), f"https://t.me/{app.username}?start=help")]
    )


SETTINGS_TOGGLES: Final[tuple[tuple[str, str, str], ...]] = (
    ("direct", "ui.settings.search_button", "MODECHANGE|SEARCHANSWER"),
    ("admin_commands", "ui.settings.commands_button", "AUTHMODECHANGE|AUTHANSWER"),
    ("admin_playback", "ui.settings.playback_button", "PLAYTYPECHANGE|PLAYTYPEANSWER"),
)


def settings_markup(
    *,
    direct: bool = True,
    admin_commands: bool = True,
    admin_playback: bool = True,
    with_language: bool = False,
) -> InlineKeyboardMarkup:
    info = _label("ui.settings.info_button")
    state = {
        "direct": direct,
        "admin_commands": admin_commands,
        "admin_playback": admin_playback,
    }
    rows: ButtonRows = []
    for flag, label_key, actions in SETTINGS_TOGGLES:
        change, explain = actions.split("|")
        current = state[flag]
        access = "admins" if current else "everyone"
        rows.append(
            [
                _callback(
                    _label(label_key, access=_label(f"ui.settings.{access}")),
                    change,
                    SUCCESS if current else PRIMARY,
                ),
                _callback(info, explain),
            ]
        )
    if with_language:
        rows.append([_callback(_label("ui.settings.language_button"), "LANGUAGESETTINGS")])
    rows.append([_callback(_label("ui.settings.close_button"), "close", DANGER)])
    return InlineKeyboardMarkup(rows)


def language_markup(current: str, options: Sequence[tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons = [
        _callback(
            ("✓ " if code == current else "") + label,
            f"LANGSET:{code}",
            SUCCESS if code == current else PRIMARY,
        )
        for code, label in options
    ]
    rows = _grid(buttons)
    rows.append([_back_button("LANGUAGEBACK")])
    return InlineKeyboardMarkup(rows)


def autoplay_markup(enabled: bool) -> InlineKeyboardMarkup:
    return _markup(
        [
            _callback(_label("autoplay.on"), "AUTOPLAY:ON", SUCCESS if enabled else PRIMARY),
            _callback(_label("autoplay.off"), "AUTOPLAY:OFF", DANGER if not enabled else PRIMARY),
        ],
        [_close_button()],
    )


def stats_buttons() -> InlineKeyboardMarkup:
    return _markup(
        [_callback(_label("ui.buttons.refresh"), "stats_back")],
        [
            _link(_label("ui.buttons.support_group"), config.SUPPORT_CHAT),
            _close_button(),
        ],
    )


def back_stats_buttons() -> InlineKeyboardMarkup:
    return _markup([_back_button("stats_back"), _close_button()])


__all__ = [
    "about_markup",
    "aq_markup",
    "autoplay_markup",
    "back_stats_buttons",
    "botplaylist_markup",
    "close_markup",
    "group_invite_url",
    "help_menu_markup",
    "help_section_markup",
    "help_section_order",
    "help_topic_entries",
    "language_markup",
    "livestream_markup",
    "playlist_markup",
    "private_help_panel",
    "private_panel",
    "queue_back_markup",
    "queue_markup",
    "settings_markup",
    "slider_markup",
    "speed_markup",
    "start_panel",
    "stats_buttons",
    "stream_markup",
    "supp_markup",
    "track_info_markup",
    "track_markup",
]
