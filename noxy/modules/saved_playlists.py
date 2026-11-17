from __future__ import annotations

import logging
import secrets
import string
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pyrogram import filters
from pyrogram.types import Message

from noxy import YouTube, app, db
from noxy.core.i18n import get_text
from noxy.core.limits import PLAYLIST_FETCH_LIMIT, QUEUE_LIMIT
from noxy.core.state import adminlist
from noxy.database import get_playtype, is_active_chat, mongodb
from noxy.helpers.stream import stream

LOGGER = logging.getLogger(__name__)

playlists = mongodb.saved_playlists
CODE_ALPHABET = string.ascii_uppercase + string.digits
CODE_LENGTH = 6
CODE_ATTEMPTS = 10
NAME_LIMIT = 48
LIST_LIMIT = 25
TITLE_SNIPPET = 70


@dataclass(frozen=True, slots=True)
class SavedPlaylist:
    id: Any
    name: str
    code: str
    tracks: tuple[Any, ...]

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> SavedPlaylist:
        return cls(
            id=document.get("_id"),
            name=str(document.get("name") or ""),
            code=str(document.get("code") or ""),
            tracks=tuple(document.get("tracks") or []),
        )

    @property
    def is_full(self) -> bool:
        return len(self.tracks) >= PLAYLIST_FETCH_LIMIT


def _args(message: Message) -> str:
    return message.text.split(None, 1)[1].strip() if len(message.command) > 1 else ""


async def _new_code() -> str:
    for _ in range(CODE_ATTEMPTS):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
        if not await playlists.find_one({"code": code}, {"_id": 1}):
            return code
    raise RuntimeError("Could not allocate a unique playlist code")


async def _owned_playlist(code: str, user_id: int) -> SavedPlaylist | None:
    document = await playlists.find_one({"code": code.upper(), "owner_id": user_id})
    return SavedPlaylist.from_document(document) if document else None


@app.on_message(filters.command(["Addpl", "addpl", "addplaylist"]))
async def add_playlist(_, message: Message):
    if not message.from_user:
        return await message.reply_text(get_text("saved_playlists.user_only"))

    args = _args(message)
    if not args:
        return await message.reply_text(get_text("saved_playlists.add_usage"))

    parts = args.split(None, 1)
    if len(parts) == 2 and len(parts[0]) == CODE_LENGTH and all(
        character in CODE_ALPHABET for character in parts[0].upper()
    ):
        code, query = parts
        saved = await _owned_playlist(code, message.from_user.id)
        if saved:
            if saved.is_full:
                return await message.reply_text(
                    get_text("saved_playlists.track_limit", limit=PLAYLIST_FETCH_LIMIT)
                )
            try:
                details, _ = await YouTube.track(query.strip())
            except Exception:
                LOGGER.debug("Could not resolve saved playlist track: %r", query, exc_info=True)
                return await message.reply_text(get_text("playCommand.track_fetch_failed"))
            if not details.get("vidid") or not details.get("duration_sec"):
                return await message.reply_text(get_text("playCommand.track_fetch_failed"))
            stored_track = {
                "title": str(details["title"]),
                "vidid": str(details["vidid"]),
                "link": str(details.get("link") or ""),
                "duration_min": str(details["duration_min"]),
                "duration_sec": int(details["duration_sec"]),
            }
            tracks = [*saved.tracks, stored_track]
            result = await playlists.update_one(
                {"_id": saved.id, "owner_id": message.from_user.id},
                {"$set": {"tracks": tracks}},
            )
            if not result.modified_count:
                return await message.reply_text(get_text("saved_playlists.not_found"))
            return await message.reply_text(
                get_text(
                    "saved_playlists.track_added",
                    name=saved.name,
                    code=saved.code,
                    count=len(tracks),
                )
            )
        existing = await playlists.find_one({"code": code.upper()}, {"_id": 1})
        if existing:
            return await message.reply_text(get_text("saved_playlists.not_found"))

    name = args.strip()
    if len(name) > NAME_LIMIT:
        return await message.reply_text(get_text("saved_playlists.name_too_long"))
    if await playlists.find_one({"owner_id": message.from_user.id, "name_key": name.casefold()}):
        return await message.reply_text(get_text("saved_playlists.name_exists"))

    code = await _new_code()
    await playlists.insert_one({
        "owner_id": message.from_user.id,
        "name": name,
        "name_key": name.casefold(),
        "code": code,
        "tracks": [],
        "created_at": datetime.now(UTC),
    })
    await message.reply_text(get_text("saved_playlists.created", name=name, code=code))


@app.on_message(filters.command(["delpl", "deletepl", "delplaylist"]))
async def delete_playlist(_, message: Message):
    if not message.from_user:
        return await message.reply_text(get_text("saved_playlists.user_only"))
    code = _args(message).split(None, 1)[0].upper() if _args(message) else ""
    if not code:
        return await message.reply_text(get_text("saved_playlists.delete_usage"))
    result = await playlists.delete_one({"code": code, "owner_id": message.from_user.id})
    if not result.deleted_count:
        return await message.reply_text(get_text("saved_playlists.not_found"))
    await message.reply_text(get_text("saved_playlists.deleted", code=code))


@app.on_message(filters.command(["Playlist", "playlist", "myplaylists"]))
async def manage_playlists(_, message: Message):
    if not message.from_user:
        return await message.reply_text(get_text("saved_playlists.user_only"))

    args = _args(message)
    if not args:
        return await _list_playlists(message)

    code = args.split(None, 1)[0].upper()
    document = await playlists.find_one({"code": code})
    if not document:
        return await message.reply_text(get_text("saved_playlists.not_found"))
    saved = SavedPlaylist.from_document(document)
    if not saved.tracks:
        return await message.reply_text(
            get_text("saved_playlists.no_tracks", name=saved.name, code=saved.code)
        )
    if message.chat.id > 0:
        return await message.reply_text(get_text("saved_playlists.group_only"))
    if not await _may_play(message):
        return None

    tracks = list(saved.tracks[: QUEUE_LIMIT])
    mystic = await message.reply_text(get_text("saved_playlists.loading", name=saved.name))
    added = 0
    failed = 0
    for saved_track in tracks:
        if await is_active_chat(message.chat.id) and len(db.get(message.chat.id, [])) >= QUEUE_LIMIT:
            failed += len(tracks) - added - failed
            break
        try:
            if isinstance(saved_track, dict):
                details = {
                    "title": str(saved_track.get("title") or ""),
                    "vidid": str(saved_track.get("vidid") or ""),
                    "link": str(saved_track.get("link") or ""),
                    "duration_min": str(saved_track.get("duration_min") or ""),
                    "duration_sec": int(saved_track.get("duration_sec") or 0),
                }
                if not details["vidid"]:
                    raise ValueError("Saved playlist item has no YouTube video ID")
            else:
                details, _ = await YouTube.track(str(saved_track))
            if not details.get("title") or not details.get("duration_min") or not details.get("vidid"):
                failed += 1
                continue
            before = len(db.get(message.chat.id, []))
            await stream(
                mystic,
                message.from_user.id,
                details,
                message.chat.id,
                message.from_user.first_name,
                message.chat.id,
                streamtype="youtube",
            )
            after = len(db.get(message.chat.id, []))
            if after > before:
                added += 1
            else:
                failed += 1
        except Exception:
            LOGGER.debug("Saved playlist track failed: code=%s", code, exc_info=True)
            failed += 1

    if added:
        await mystic.edit_text(
            get_text("saved_playlists.play_started", name=saved.name, added=added, failed=failed)
        )
    else:
        await mystic.edit_text(get_text("saved_playlists.play_failed", failed=failed))
    return None


async def _list_playlists(message: Message) -> None:
    rows = [
        get_text(
            "saved_playlists.list_item",
            name=item["name"],
            code=item["code"],
            count=len(item.get("tracks") or []),
        )
        async for item in playlists.find(
            {"owner_id": message.from_user.id},
            {"name": 1, "code": 1, "tracks": 1},
        ).sort("created_at", -1).limit(LIST_LIMIT)
    ]
    if not rows:
        return await message.reply_text(get_text("saved_playlists.empty"))
    return await message.reply_text(
        get_text("saved_playlists.list_title", count=len(rows))
        + "\n\n"
        + "\n".join(rows)
        + "\n\n"
        + get_text("saved_playlists.list_help")
    )


async def _may_play(message: Message) -> bool:
    if await get_playtype(message.chat.id) == "Everyone":
        return True
    admins = adminlist.get(message.chat.id)
    if not admins:
        await message.reply_text(get_text("play_wrapper.admin_cache"))
        return False
    if message.from_user.id not in admins:
        await message.reply_text(get_text("play_wrapper.admins_only"))
        return False
    return True
