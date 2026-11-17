from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pyrogram.types import LinkPreviewOptions

from noxy import YouTube, app, db
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.core.limits import DURATION_LIMIT, PLAYLIST_FETCH_LIMIT, QUEUE_LIMIT
from noxy.database import add_active_video_chat, is_active_chat
from noxy.helpers.errors import AssistantErr
from noxy.helpers.formatting import seconds_to_min
from noxy.helpers.keyboards import aq_markup, close_markup, stream_markup
from noxy.helpers.pastebin import paste
from noxy.helpers.queue import put_queue, put_queue_index

LOGGER = logging.getLogger(__name__)

PREVIEW_OFF = LinkPreviewOptions(is_disabled=True)
INFO_DEEP_LINK = "https://t.me/{bot}?start=info_{vid}"


@dataclass(frozen=True, slots=True)
class _Track:
    file: str
    title: str
    duration: str
    vidid: str
    video: bool
    seconds: int = 0

    @property
    def kind(self) -> str:
        return "video" if self.video else "audio"

    @property
    def markup_hint(self) -> str:
        return "stream" if self.file.startswith("vid_") else "tg"


def _deep_link(vidid: str) -> str:
    return INFO_DEEP_LINK.format(bot=app.username, vid=vidid)


async def _queue_limit_notice(original_chat_id: int) -> None:
    await app.send_message(
        original_chat_id,
        get_text("stream.queue_limit", limit=QUEUE_LIMIT),
    )


async def _announce_started(
    original_chat_id: int,
    track: _Track,
    user_name: str,
    chat_id: int,
    *,
    link: str | None = None,
) -> None:
    text = get_text("stream.started_streaming_positional").format(
        link or _deep_link(track.vidid),
        track.title[:30],
        track.duration,
        user_name,
    )
    card = await app.send_message(
        original_chat_id,
        text=text,
        reply_markup=stream_markup(chat_id),
        link_preview_options=PREVIEW_OFF,
    )
    entry = db.get(chat_id)
    if entry:
        entry[0]["mystic"] = card
        entry[0]["markup"] = track.markup_hint


async def _announce_queued(
    original_chat_id: int,
    chat_id: int,
    track: _Track,
    user_name: str,
    position: int,
) -> None:
    await app.send_message(
        chat_id=original_chat_id,
        text=get_text("stream.queued_track_positional").format(
            position, track.title[:27], track.duration, user_name
        ),
        reply_markup=aq_markup(chat_id),
    )


async def _enqueue(
    track: _Track,
    chat_id: int,
    original_chat_id: int,
    user_name: str,
    user_id: int,
    *,
    forceplay: bool | str | None,
    index_mode: bool = False,
) -> None:
    if await is_active_chat(chat_id):
        if index_mode:
            inserted = await put_queue_index(
                chat_id,
                original_chat_id,
                track.file,
                track.title,
                track.duration,
                user_name,
                track.vidid,
                track.kind,
                max_size=QUEUE_LIMIT,
            )
        else:
            inserted = await put_queue(
                chat_id,
                original_chat_id,
                track.file,
                track.title,
                track.duration,
                user_name,
                track.vidid,
                user_id,
                track.kind,
                max_size=QUEUE_LIMIT,
            )
        if not inserted:
            return await _queue_limit_notice(original_chat_id)
        position = len(db.get(chat_id, [])) - 1
        return await _announce_queued(original_chat_id, chat_id, track, user_name, position)

    if not forceplay:
        db[chat_id] = []
    await noxy.join_call(chat_id, original_chat_id, track.file, video=track.video or None)
    await put_queue(
        chat_id,
        original_chat_id,
        track.file,
        track.title,
        track.duration,
        user_name,
        track.vidid,
        user_id,
        track.kind,
        forceplay=forceplay,
    )
    if index_mode and track.video:
        await add_active_video_chat(chat_id)
    await _announce_started(original_chat_id, track, user_name, chat_id)


async def stream(
    mystic,
    user_id: int,
    result: Any,
    chat_id: int,
    user_name: str,
    original_chat_id: int,
    video: bool | str | None = None,
    streamtype: bool | str | None = None,
    spotify: bool | str | None = None,
    forceplay: bool | str | None = None,
) -> None:
    if not result:
        return
    if forceplay:
        await noxy.force_stop_stream(chat_id)

    if streamtype == "playlist":
        return await _stream_playlist(
            mystic,
            user_id,
            result,
            chat_id,
            user_name,
            original_chat_id,
            video=video,
            spotify=spotify,
            forceplay=forceplay,
        )
    if streamtype == "index":
        return await _enqueue(
            _Track(file="index_url", title=get_text("stream.index_title"), duration="00:00",
                   vidid=str(result), video=bool(video)),
            chat_id,
            original_chat_id,
            user_name,
            user_id,
            forceplay=forceplay,
            index_mode=True,
        )
    if streamtype == "live":
        return await _stream_live(
            result, chat_id, original_chat_id, user_id, user_name, video=video,
            forceplay=forceplay,
        )
    if streamtype == "soundcloud":
        track = _Track(
            file=str(result["filepath"]),
            title=str(result["title"]),
            duration=str(result["duration_min"]),
            vidid="soundcloud",
            video=False,
        )
        return await _enqueue(
            track, chat_id, original_chat_id, user_name, user_id, forceplay=forceplay
        )
    if streamtype == "telegram":
        track = _Track(
            file=str(result["path"]),
            title=str(result["title"]).title(),
            duration=str(result["dur"]),
            vidid="telegram",
            video=bool(video),
        )
        return await _enqueue(
            track, chat_id, original_chat_id, user_name, user_id, forceplay=forceplay
        )
    return await _stream_youtube(
        mystic, user_id, result, chat_id, user_name, original_chat_id,
        video=video, forceplay=forceplay,
    )


async def _stream_youtube(
    mystic,
    user_id: int,
    result: dict,
    chat_id: int,
    user_name: str,
    original_chat_id: int,
    *,
    video: bool | str | None,
    forceplay: bool | str | None,
) -> None:
    vidid = str(result["vidid"])
    try:
        file_path = await YouTube.download(vidid, mystic, video=bool(video))
    except Exception as exc:
        LOGGER.exception("Download failed for %s", vidid)
        raise AssistantErr(get_text("stream.track_fetch_failed")) from exc

    track = _Track(
        file=str(file_path or f"vid_{vidid}"),
        title=str(result["title"]).title(),
        duration=str(result["duration_min"]),
        vidid=vidid,
        video=bool(video),
        seconds=0,
    )
    await _enqueue(track, chat_id, original_chat_id, user_name, user_id, forceplay=forceplay)


async def _stream_live(
    result: dict,
    chat_id: int,
    original_chat_id: int,
    user_id: int,
    user_name: str,
    *,
    video: bool | str | None,
    forceplay: bool | str | None,
) -> None:
    vidid = str(result["vidid"])
    track = _Track(
        file=f"live_{vidid}",
        title=str(result["title"]).title(),
        duration=get_text("stream.live_track"),
        vidid=vidid,
        video=bool(video),
    )
    if await is_active_chat(chat_id):
        return await _enqueue(
            track, chat_id, original_chat_id, user_name, user_id, forceplay=forceplay
        )

    if not forceplay:
        db[chat_id] = []
    status, file_path = await YouTube.video(str(result["link"]))
    if status == 0:
        raise AssistantErr(get_text("stream.no_live_video"))
    live = _Track(
        file=str(file_path),
        title=track.title,
        duration=track.duration,
        vidid=vidid,
        video=track.video,
    )
    await noxy.join_call(chat_id, original_chat_id, live.file, video=live.video or None)
    await put_queue(
        chat_id,
        original_chat_id,
        track.file,
        track.title,
        track.duration,
        user_name,
        vidid,
        user_id,
        track.kind,
        forceplay=forceplay,
    )
    await _announce_started(original_chat_id, live, user_name, chat_id)


async def _stream_playlist(
    mystic,
    user_id: int,
    result: Any,
    chat_id: int,
    user_name: str,
    original_chat_id: int,
    *,
    video: bool | str | None,
    spotify: bool | str | None,
    forceplay: bool | str | None,
) -> None:
    items = list(result)[: PLAYLIST_FETCH_LIMIT]
    queued_before = len(db.get(chat_id) or []) if await is_active_chat(chat_id) else 0
    capacity = max(0, QUEUE_LIMIT - queued_before)
    limit = min(PLAYLIST_FETCH_LIMIT, capacity)
    if limit <= 0:
        return await _queue_limit_notice(original_chat_id)

    listing = get_text("stream.playlist_header")
    queued = 0
    skipped = max(0, len(items) - limit)
    total_seconds = 0

    for index, search in enumerate(items[:limit]):
        try:
            title, duration_min, duration_sec, vidid = await YouTube.details(
                search, not spotify
            )
        except Exception:
            LOGGER.debug("Skipping playlist item after metadata failure", exc_info=True)
            skipped += 1
            continue
        if not title or not duration_min or duration_min == "None" or not vidid:
            skipped += 1
            continue

        seconds = int(duration_sec or 0)
        if seconds > DURATION_LIMIT:
            skipped += 1
            continue

        if await is_active_chat(chat_id):
            if len(db.get(chat_id) or []) >= QUEUE_LIMIT:
                skipped += max(0, min(limit, len(items)) - index)
                break
            inserted = await put_queue(
                chat_id,
                original_chat_id,
                f"vid_{vidid}",
                title,
                duration_min,
                user_name,
                vidid,
                user_id,
                "video" if video else "audio",
                max_size=QUEUE_LIMIT,
            )
            if not inserted:
                skipped += max(0, min(limit, len(items)) - index)
                break
            position = len(db.get(chat_id, [])) - 1
            queued += 1
            total_seconds += max(0, seconds)
            listing += f"{queued}. {title[:70]}\n"
            listing += get_text("stream.playlist_position", position=position)
            continue

        if not forceplay:
            db[chat_id] = []
        try:
            file_path = await YouTube.download(vidid, mystic, video=bool(video))
        except Exception:
            LOGGER.exception("Playlist first-track download failed for %s", vidid)
            skipped += 1
            continue
        track = _Track(
            file=str(file_path or f"vid_{vidid}"),
            title=title,
            duration=duration_min,
            vidid=vidid,
            video=bool(video),
        )
        await noxy.join_call(chat_id, original_chat_id, track.file, video=track.video or None)
        await put_queue(
            chat_id,
            original_chat_id,
            track.file,
            track.title,
            track.duration,
            user_name,
            vidid,
            user_id,
            track.kind,
            forceplay=forceplay,
        )
        await _announce_started(original_chat_id, track, user_name, chat_id)
        queued += 1
        total_seconds += max(0, seconds)

    if queued == 0:
        return await app.send_message(original_chat_id, get_text("stream.playlist_empty"))

    duration_text = seconds_to_min(total_seconds)
    link = None
    try:
        link = await paste(listing)
    except Exception:
        LOGGER.debug("Could not publish the full playlist queue", exc_info=True)

    if link:
        summary = get_text(
            "stream.playlist_summary",
            count=queued,
            skipped=skipped,
            duration=duration_text,
            url=link,
        )
    else:
        summary = get_text(
            "stream.playlist_summary_no_link",
            count=queued,
            skipped=skipped,
            duration=duration_text,
        )
    return await app.send_message(
        original_chat_id,
        text=summary,
        reply_markup=close_markup(),
        link_preview_options=PREVIEW_OFF,
    )
