from __future__ import annotations

import contextlib
import logging
import random
import string
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pyrogram import filters
from pyrogram.types import Message
from pytgcalls.exceptions import NoActiveGroupCall

from noxy import Apple, Resso, SoundCloud, Spotify, Telegram, YouTube, app, config
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.core.limits import DURATION_LIMIT, DURATION_LIMIT_MIN, PLAYLIST_FETCH_LIMIT
from noxy.core.state import lyrical
from noxy.helpers.formatting import VIDEO_EXTENSIONS, time_to_seconds
from noxy.helpers.keyboards import (
    botplaylist_markup,
    livestream_markup,
    playlist_markup,
    slider_markup,
    track_markup,
)
from noxy.helpers.play_guard import PlayWrapper
from noxy.helpers.stream import stream
from noxy.services.downloader import TG_AUDIO_FILESIZE_LIMIT, TG_VIDEO_FILESIZE_LIMIT

LOGGER = logging.getLogger(__name__)

PLAYLIST_HASH_LENGTH = 10
PLAYLIST_TYPES = frozenset({"yt", "spplay", "spalbum", "spartist", "apple"})
ASSISTANT_ERRORS = frozenset({"AssistantErr"})

play_1 = get_text("playCommand.loading")
play_3 = get_text("playCommand.failed_query")
play_4 = get_text("playCommand.admins_only")
play_5 = get_text("playCommand.audio_too_large")
play_6 = get_text("playCommand.duration_limit")
play_7 = get_text("playCommand.invalid_video_extension")
play_8 = get_text("playCommand.video_too_large")
play_9 = get_text("playCommand.playlist_prompt")
play_10 = get_text("playCommand.track_title_duration")
play_11 = get_text("playCommand.spotify_player")
play_12 = get_text("playCommand.apple_player")
play_13 = get_text("playCommand.live_prompt")
play_14 = get_text("playCommand.track_fetch_failed")
play_15 = get_text("playCommand.failed_process")
play_16 = get_text("playCommand.no_voice_chat")
play_17 = get_text("playCommand.turn_on_voice_chat")
play_18 = get_text("playCommand.usage")
play_19 = get_text("playCommand.queued_playlist")
play_20 = get_text("playCommand.queued_position")
play_21 = get_text("playCommand.playlist_added")
play_22 = get_text("playCommand.playmode_prompt")


async def _report_stream_error(mystic: Message, error: Exception) -> None:
    if type(error).__name__ in ASSISTANT_ERRORS:
        return await mystic.edit_text(str(error))
    if isinstance(error, NoActiveGroupCall):
        return await mystic.edit_text(play_16)
    LOGGER.error(
        "Playback failed with %s",
        type(error).__name__,
        exc_info=(type(error), error, error.__traceback__),
    )
    return await mystic.edit_text(play_15)


async def _stream_details(
    mystic: Message,
    user_id: int,
    details: Any,
    chat_id: int,
    user_name: str,
    original_chat_id: int,
    **options: Any,
) -> None:
    try:
        await stream(
            mystic, user_id, details, chat_id, user_name, original_chat_id, **options
        )
    except Exception as error:
        return await _report_stream_error(mystic, error)
    await mystic.delete()
    return None


@app.on_message(
    filters.command(["play", "vplay", "playforce", "vplayforce"]) & filters.group
)
@PlayWrapper
async def play_commnd(
    client,
    message: Message,
    chat_id: int,
    video: bool | None,
    playmode: str,
    url: str | None,
    fplay: bool | None,
):

    mystic = await message.reply_text(play_1)
    user_id = message.from_user.id
    user_name = message.from_user.first_name

    telegram_audio = _reply_media(message, ("audio", "voice"))
    telegram_video = _reply_media(message, ("video", "document"))
    if telegram_audio or telegram_video:
        return await _play_telegram(
            message,
            mystic,
            chat_id,
            telegram_audio or telegram_video,
            audio=telegram_audio is not None,
            user_id=user_id,
            user_name=user_name,
            fplay=fplay,
        )

    if not url:
        return await _search_flow(
            message, mystic, chat_id, user_id, user_name, playmode, video, fplay
        )

    source = await _resolve_url(url, message, mystic, user_id)
    if source is None:
        return None
    if isinstance(source, bool):
        return await _play_index(
            mystic, user_id, url, chat_id, user_name, message, video, fplay
        )
    return await _dispatch(
        mystic,
        message,
        source,
        chat_id,
        user_id,
        user_name,
        playmode=playmode,
        video=video,
        fplay=fplay,
    )


@dataclass(frozen=True, slots=True)
class _Source:
    details: dict[str, Any] | None
    streamtype: str
    track_id: str | None = None
    plist_type: str | None = None
    plist_id: Any = None
    spotify: bool | None = None
    caption: str | None = None


def _mode(fplay: bool | None) -> str:
    return "f" if fplay else "d"


def _reply_media(message: Message, attributes: tuple[str, ...]) -> Any:
    reply = message.reply_to_message
    if reply is None:
        return None
    for attribute in attributes:
        value = getattr(reply, attribute, None)
        if value:
            return value
    return None


async def _play_telegram(
    message: Message,
    mystic: Message,
    chat_id: int,
    media: Any,
    *,
    audio: bool,
    user_id: int,
    user_name: str,
    fplay: bool | None,
) -> None:
    limit = TG_AUDIO_FILESIZE_LIMIT if audio else TG_VIDEO_FILESIZE_LIMIT
    if (media.file_size or 0) > limit:
        return await mystic.edit_text(play_5 if audio else play_8)

    if not audio:
        extension = (getattr(media, "file_name", "") or "").split(".")[-1].lower()
        if extension not in VIDEO_EXTENSIONS:
            supported = " | ".join(sorted(VIDEO_EXTENSIONS))
            return await mystic.edit_text(play_7.format(supported))

    duration = int(getattr(media, "duration", 0) or 0)
    if duration > DURATION_LIMIT:
        return await mystic.edit_text(
            play_6.format(DURATION_LIMIT_MIN, app.mention)
        )

    if audio:
        file_path = await Telegram.get_filepath(audio=media)
    else:
        file_path = await Telegram.get_filepath(video=media)
    if not await Telegram.download(message, mystic, file_path):
        return None

    details = {
        "title": await Telegram.get_filename(media, audio=audio),
        "link": await Telegram.get_link(message),
        "path": file_path,
        "dur": await Telegram.get_duration(media, file_path),
    }
    await _stream_details(
        mystic,
        user_id,
        details,
        chat_id,
        user_name,
        message.chat.id,
        video=None if audio else True,
        streamtype="telegram",
        forceplay=fplay,
    )
    return None


async def _search_flow(
    message: Message,
    mystic: Message,
    chat_id: int,
    user_id: int,
    user_name: str,
    playmode: str,
    video: bool | None,
    fplay: bool | None,
) -> None:
    if len(message.command) < 2:
        return await mystic.edit_text(play_18, reply_markup=botplaylist_markup())
    query = (message.text or "").split(None, 1)[1].replace("-v", "").strip()
    try:
        details, track_id = await YouTube.track(query)
    except Exception:
        LOGGER.debug("Search failed for %r", query, exc_info=True)
        return await mystic.edit_text(play_3)

    if playmode != "Direct":
        return await mystic.edit_text(
            play_10.format(details["title"].title(), details["duration_min"]),
            reply_markup=slider_markup(track_id, user_id, query, 0, _mode(fplay)),
        )
    if not details["duration_min"]:
        return await mystic.edit_text(
            play_13,
            reply_markup=livestream_markup(
                track_id, user_id, "v" if video else "a", _mode(fplay)
            ),
        )
    await _stream_details(
        mystic,
        user_id,
        details,
        chat_id,
        user_name,
        message.chat.id,
        video=video,
        streamtype="youtube",
        forceplay=fplay,
    )
    return None


def _is_http(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


async def _resolve_url(
    url: str, message: Message, mystic: Message, user_id: int
) -> _Source | bool | None:
    if await YouTube.exists(url) or not _is_http(url):
        if "playlist" in url:
            try:
                await YouTube.playlist(url, PLAYLIST_FETCH_LIMIT, user_id)
            except Exception:
                LOGGER.debug("Playlist lookup failed for %s", url, exc_info=True)
                await mystic.edit_text(play_3)
                return None
            return _Source(
                details=None,
                streamtype="playlist",
                plist_type="yt",
                plist_id=url.split("list=")[-1].split("&")[0],
                caption=play_9,
            )
        try:
            details, track_id = await YouTube.track(url)
        except Exception:
            LOGGER.debug("Track lookup failed for %s", url, exc_info=True)
            await mystic.edit_text(play_3)
            return None
        return _Source(
            details=details,
            streamtype="youtube",
            track_id=track_id,
            caption=play_10.format(details["title"], details["duration_min"]),
        )

    if await Spotify.valid(url):
        return await _resolve_spotify(url, mystic)
    if await Apple.valid(url):
        return await _resolve_apple(url, mystic, message)
    if await Resso.valid(url):
        try:
            details, _ = await Resso.track(url)
        except Exception:
            LOGGER.debug("Resso lookup failed", exc_info=True)
            await mystic.edit_text(play_3)
            return None
        return _Source(details=details, streamtype="youtube")
    if await SoundCloud.valid(url):
        return _Source(details=None, streamtype="soundcloud", track_id=url)
    return True


async def _resolve_spotify(url: str, mystic: Message) -> _Source | None:
    try:
        if "track" in url:
            details, track_id = await Spotify.track(url)
            return _Source(
                details=details,
                streamtype="youtube",
                track_id=track_id,
                caption=play_10.format(details["title"], details["duration_min"]),
            )
        for marker, plist_type in (
            ("playlist", "spplay"),
            ("album", "spalbum"),
            ("artist", "spartist"),
        ):
            if marker in url:
                _details, plist_id = await getattr(Spotify, marker)(url)
                return _Source(
                    details=None,
                    streamtype="playlist",
                    plist_type=plist_type,
                    plist_id=plist_id,
                    spotify=True,
                    caption=play_11.format(app.mention, ""),
                )
    except Exception:
        LOGGER.debug("Spotify lookup failed for %s", url, exc_info=True)
        await mystic.edit_text(play_3)
        return None
    await mystic.edit_text(play_15)
    return None


async def _resolve_apple(url: str, mystic: Message, message: Message) -> _Source | None:
    try:
        if "album" in url:
            details, track_id = await Apple.track(url)
            return _Source(
                details=details,
                streamtype="youtube",
                track_id=track_id,
                caption=play_10.format(details["title"], details["duration_min"]),
            )
        if "playlist" in url:
            _details, plist_id = await Apple.playlist(url)
            return _Source(
                details=None,
                streamtype="playlist",
                plist_type="apple",
                plist_id=plist_id,
                spotify=True,
                caption=play_12.format(app.mention, message.from_user.mention),
            )
    except Exception:
        LOGGER.debug("Apple lookup failed for %s", url, exc_info=True)
        await mystic.edit_text(play_3)
        return None
    await mystic.edit_text(play_3)
    return None


async def _play_index(
    mystic: Message,
    user_id: int,
    url: str,
    chat_id: int,
    user_name: str,
    message: Message,
    video: bool | None,
    fplay: bool | None,
) -> None:
    try:
        await noxy.stream_call(url)
    except NoActiveGroupCall:
        await mystic.edit_text(get_text("playCommand.generic_error"))
        if config.LOGGER_ID:
            with contextlib.suppress(Exception):
                await app.send_message(chat_id=config.LOGGER_ID, text=play_17)
        return None
    except Exception as error:
        LOGGER.error(
            "Index stream failed with %s",
            type(error).__name__,
            exc_info=(type(error), error, error.__traceback__),
        )
        return await mystic.edit_text(play_15)

    await mystic.edit_text(get_text("playCommand.processing"))
    return await _stream_details(
        mystic,
        user_id,
        url,
        chat_id,
        user_name,
        message.chat.id,
        video=video,
        streamtype="index",
        forceplay=fplay,
    )


async def _dispatch(
    mystic: Message,
    message: Message,
    source: _Source,
    chat_id: int,
    user_id: int,
    user_name: str,
    *,
    playmode: str,
    video: bool | None,
    fplay: bool | None,
) -> None:
    mode_flag = _mode(fplay)
    if source.streamtype == "playlist":
        token = _playlist_hash(source.plist_id)
        await mystic.delete()
        return await message.reply_text(
            text=source.caption or play_9,
            reply_markup=playlist_markup(
                token, user_id, source.plist_type or "yt", mode_flag
            ),
        )

    if source.streamtype == "soundcloud":
        details, _path = await SoundCloud.download(source.track_id or "")
        if details["duration_sec"] > DURATION_LIMIT:
            return await mystic.edit_text(
                play_6.format(DURATION_LIMIT_MIN, app.mention)
            )
        await _stream_details(
            mystic,
            user_id,
            details,
            chat_id,
            user_name,
            message.chat.id,
            streamtype="soundcloud",
            forceplay=fplay,
        )
        return None

    details = source.details or {}
    if playmode != "Direct":
        await mystic.delete()
        return await message.reply_text(
            text=source.caption or play_9,
            reply_markup=track_markup(source.track_id or "", user_id, mode_flag),
        )

    if not details.get("duration_min"):
        return await mystic.edit_text(
            play_13,
            reply_markup=livestream_markup(
                source.track_id or "", user_id, "v" if video else "a", mode_flag
            ),
        )
    if time_to_seconds(details["duration_min"]) > DURATION_LIMIT:
        return await mystic.edit_text(
            play_6.format(DURATION_LIMIT_MIN, app.mention)
        )
    await _stream_details(
        mystic,
        user_id,
        details,
        chat_id,
        user_name,
        message.chat.id,
        video=video,
        streamtype=source.streamtype,
        spotify=source.spotify,
        forceplay=fplay,
    )
    return None


def _playlist_hash(plist_id: Any) -> str:
    token = "".join(
        random.choices(string.ascii_uppercase + string.digits, k=PLAYLIST_HASH_LENGTH)
    )
    lyrical[token] = plist_id
    return token



@app.on_callback_query(filters.regex(r"^MusicStream\s+"))
async def play_music(client, query: Message):
    callback_data = (query.data or "").strip()
    parts = callback_data.split(None, 1)
    if len(parts) != 2:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    payload = parts[1].split("|")
    if len(payload) != 4:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    vidid, raw_user_id, mode, fplay = payload
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    if not vidid or mode not in {"a", "v"} or fplay not in {"f", "d"}:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    if query.from_user.id != user_id:
        try:
            return await query.answer(get_text("playCommand.not_for_user"), show_alert=True)
        except Exception:
            return
    chat_id = query.message.chat.id
    user_name = query.from_user.first_name
    with contextlib.suppress(Exception):
        await query.message.delete()
    with contextlib.suppress(Exception):
        await query.answer()
    mystic = await query.message.reply_text(play_1)
    try:
        details, track_id = await YouTube.track(vidid, True)
    except Exception:
        LOGGER.debug("Track lookup failed for %s", vidid, exc_info=True)
        return await mystic.edit_text(play_3)
    if details["duration_min"]:
        duration_sec = time_to_seconds(details["duration_min"])
        if duration_sec > DURATION_LIMIT:
            return await mystic.edit_text(
                play_6.format(DURATION_LIMIT_MIN, app.mention)
            )
    else:
        return await mystic.edit_text(
            play_13,
            reply_markup=livestream_markup(
                track_id,
                query.from_user.id,
                mode,
                "f" if fplay else "d",
            ),
        )
    video = True if mode == "v" else None
    ffplay = True if fplay == "f" else None
    try:
        await stream(
            mystic,
            query.from_user.id,
            details,
            chat_id,
            user_name,
            query.message.chat.id,
            video,
            streamtype="youtube",
            forceplay=ffplay,
        )
    except Exception as error:
        return await _report_stream_error(mystic, error)
    return await mystic.delete()


@app.on_callback_query(filters.regex("AnonymousAdmin"))
async def anonymous_check(client, query):
    with contextlib.suppress(Exception):
        await query.answer(
            get_text("playCommand.anonymous_admin_help"),
            show_alert=True,
        )


@app.on_callback_query(filters.regex(r"^ShizukuPlaylists\s+"))
async def play_playlists_command(client, query):
    callback_data = (query.data or "").strip()
    parts = callback_data.split(None, 1)
    if len(parts) != 2:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    payload = parts[1].split("|")
    if len(payload) != 5:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    videoid, raw_user_id, ptype, mode, fplay = payload
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    if not videoid or ptype not in PLAYLIST_TYPES:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    if mode not in {"a", "v"} or fplay not in {"f", "d"}:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    if query.from_user.id != int(user_id):
        return await query.answer(get_text("playCommand.not_for_user"), show_alert=True)
    chat_id = query.message.chat.id
    user_name = query.from_user.first_name
    with contextlib.suppress(Exception):
        await query.message.delete()
    with contextlib.suppress(Exception):
        await query.answer()
    mystic = await query.message.reply_text(play_1)
    playlist_id = lyrical.get(videoid)
    video = True if mode == "v" else None
    ffplay = True if fplay == "f" else None
    spotify = ptype != "yt"

    loaders = {
        "yt": lambda: YouTube.playlist(
            playlist_id, PLAYLIST_FETCH_LIMIT, query.from_user.id, True
        ),
        "spplay": lambda: Spotify.playlist(playlist_id),
        "spalbum": lambda: Spotify.album(playlist_id),
        "spartist": lambda: Spotify.artist(playlist_id),
        "apple": lambda: Apple.playlist(playlist_id, True),
    }
    try:
        loaded = await loaders[ptype]()
    except Exception:
        LOGGER.debug("Playlist %s could not be loaded", ptype, exc_info=True)
        return await mystic.edit_text(play_3)
    result = loaded[0] if isinstance(loaded, tuple) else loaded

    try:
        await stream(
            mystic,
            user_id,
            result,
            chat_id,
            user_name,
            query.message.chat.id,
            video=video,
            streamtype="playlist",
            spotify=spotify,
            forceplay=ffplay,
        )
    except Exception as error:
        return await _report_stream_error(mystic, error)
    return await mystic.delete()


@app.on_callback_query(filters.regex(r"^slider\s+"))
async def slider_queries(client, query):
    parts = (query.data or "").strip().split(None, 1)
    if len(parts) != 2:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    payload = parts[1].split("|")
    if len(payload) != 5:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)

    direction, raw_type, term, raw_user_id, fplay = payload
    try:
        current = int(raw_type)
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    if not term or direction not in {"F", "B"} or not 0 <= current <= 9:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    if fplay not in {"f", "d"}:
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)
    if query.from_user.id != user_id:
        return await query.answer(get_text("playCommand.not_for_user"), show_alert=True)

    if direction == "F":
        target = 0 if current == 9 else current + 1
    else:
        target = 9 if current == 0 else current - 1

    with contextlib.suppress(Exception):
        await query.answer(get_text("playCommand.wait"))
    try:
        title, duration_min, vidid = await YouTube.slider(term, target)
    except Exception:
        LOGGER.debug("Slider lookup failed for %r", term, exc_info=True)
        return await query.answer(get_text("playCommand.failed_query"), show_alert=True)

    return await query.edit_message_text(
        text=play_10.format(title.title(), duration_min),
        reply_markup=slider_markup(vidid, user_id, term, target, fplay),
    )
