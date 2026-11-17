from __future__ import annotations

import asyncio
import contextlib
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, LinkPreviewOptions, Voice

from noxy import config
from noxy.core.i18n import get_text
from noxy.helpers.formatting import (
    check_duration,
    convert_bytes,
    get_readable_time,
    seconds_to_min,
)

CHARS_LIMIT = 4096
SAFE_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}")
PROGRESS_MILESTONES = (5, 10, 20, 40, 66, 80, 99)
MAX_SPLIT_MESSAGES = 3
DOWNLOADS_DIR = Path("downloads")


def _app() -> Any:
    from noxy import app

    return app


def _cancel_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=get_text("download.cancel"), callback_data="stop_downloading"
                )
            ]
        ]
    )


@dataclass(slots=True)
class _Progress:
    message_id: int
    started: float = field(default_factory=time.monotonic)
    milestones: set[int] = field(default_factory=lambda: set(PROGRESS_MILESTONES))

    def snapshot(self, current: int, total: int) -> tuple[int, str, str, str, str] | None:
        if total <= 0 or current >= total:
            return None
        elapsed = time.monotonic() - self.started
        if elapsed <= 0:
            return None
        speed = current / elapsed
        if speed <= 0:
            return None
        percent = int(current * 100 / total)
        milestone = next((value for value in PROGRESS_MILESTONES if percent <= value), None)
        if milestone is None or milestone not in self.milestones:
            return None
        self.milestones.discard(milestone)
        eta = get_readable_time(int((total - current) / speed)) or "0 seconds"
        return (
            percent,
            convert_bytes(total),
            convert_bytes(current),
            convert_bytes(speed),
            eta,
        )


class TeleAPI:
    def __init__(self) -> None:
        self.chars_limit = CHARS_LIMIT

    async def send_split_text(self, message: Any, string: str) -> bool:
        chunks = [
            string[index : index + self.chars_limit]
            for index in range(0, len(string), self.chars_limit)
        ]
        for chunk in chunks[:MAX_SPLIT_MESSAGES]:
            await message.reply_text(
                chunk, link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
        return True

    async def get_link(self, message: Any) -> str | None:
        return message.link

    async def get_filename(self, file: Any, audio: bool | str | None = None) -> str:
        key = "download.audio_name" if audio else "download.video_name"
        return getattr(file, "file_name", None) or get_text(key)

    async def get_duration(self, file: Any, file_path: str) -> str:
        duration = getattr(file, "duration", None)
        if duration:
            return seconds_to_min(duration)
        try:
            return seconds_to_min(await check_duration(file_path))
        except (OSError, RuntimeError, ValueError):
            return get_text("download.unknown_duration")

    @staticmethod
    def _extension(name: str | None, fallback: str) -> str:
        extension = os.path.splitext(os.path.basename(name or ""))[1].lower()
        return extension if SAFE_EXTENSION.fullmatch(extension) else fallback

    async def get_filepath(
        self,
        audio: Any = None,
        video: Any = None,
    ) -> str:
        if audio:
            name = getattr(audio, "file_name", "") or ""
            fallback = ".ogg" if isinstance(audio, Voice) else ".mp3"
            file_name = f"{audio.file_unique_id}{self._extension(name, fallback)}"
        elif video:
            name = getattr(video, "file_name", "") or ""
            file_name = f"{video.file_unique_id}{self._extension(name, '.mp4')}"
        else:
            raise ValueError("An audio or video Telegram file is required.")

        return str(DOWNLOADS_DIR.resolve() / file_name)

    async def download(self, message: Any, mystic: Any, fname: str) -> bool:
        os.makedirs(os.path.dirname(os.path.abspath(fname)), exist_ok=True)
        if os.path.exists(fname):
            return True

        progress = _Progress(message.id)
        markup = _cancel_markup()

        async def on_progress(current: int, total: int) -> None:
            snapshot = progress.snapshot(current, total)
            if snapshot is None:
                return
            percent, total_size, done, speed, eta = snapshot
            with contextlib.suppress(Exception):
                await mystic.edit_text(
                    text=get_text("download.progress").format(
                        bot=_app().mention,
                        total=total_size,
                        done=done,
                        percent=percent,
                        speed=speed,
                        eta=eta,
                    ),
                    reply_markup=markup,
                )

        async def transfer() -> None:
            try:
                await _app().download_media(
                    message.reply_to_message,
                    file_name=fname,
                    progress=on_progress,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                await mystic.edit_text(get_text("download.failed"))
                return
            elapsed = get_readable_time(int(time.monotonic() - progress.started))
            await mystic.edit_text(get_text("download.done", elapsed=elapsed))

        task = asyncio.create_task(transfer(), name=f"miko-telegram-{message.id}")
        config.lyrical[mystic.id] = task
        try:
            await task
        except asyncio.CancelledError:
            config.lyrical.pop(mystic.id, None)
            return False
        finally:
            config.lyrical.pop(mystic.id, None)
        return os.path.exists(fname)
