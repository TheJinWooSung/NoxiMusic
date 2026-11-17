from __future__ import annotations

import asyncio
import contextlib
import logging
import os

from ntgcalls import ConnectionError as NtgConnectionError
from ntgcalls import TelegramServerError
from pytgcalls.exceptions import NoActiveGroupCall, NotInCallError
from pytgcalls.types import MediaStream

from noxy import config, db
from noxy.core.i18n import get_text
from noxy.core.settings import AUTO_LEAVING_ASSISTANT
from noxy.database import (
    add_active_chat,
    add_active_video_chat,
    music_on,
    remove_active_chat,
    remove_active_video_chat,
)
from noxy.helpers.errors import AssistantErr
from noxy.services.track import QueueItem

from .streams import SPEED_FACTORS, stream_for

LOGGER = logging.getLogger(__name__)


class CallControlsMixin:
    async def pause_stream(self, chat_id: int) -> None:
        client = await self.assistant(chat_id)
        await client.pause(chat_id)

    async def resume_stream(self, chat_id: int) -> None:
        client = await self.assistant(chat_id)
        await client.resume(chat_id)

    async def stop_stream(self, chat_id: int) -> None:
        async with self.lock(chat_id):
            client = await self.assistant(chat_id)
            with contextlib.suppress(Exception):
                await client.leave_call(chat_id)
            await self._clear(chat_id)

    async def force_stop_stream(self, chat_id: int) -> None:
        async with self.lock(chat_id):
            db[chat_id] = []
            await remove_active_video_chat(chat_id)
            await remove_active_chat(chat_id)
            client = await self.assistant(chat_id)
            with contextlib.suppress(Exception):
                await client.leave_call(chat_id)

    async def stop_stream_force(self, chat_id: int) -> None:
        for session_string, client in self.calls:
            if not session_string:
                continue
            with contextlib.suppress(Exception):
                await client.leave_call(chat_id)
        await self._clear(chat_id)

    async def skip_stream(self, chat_id: int, link: str, video: bool | str | None = None) -> None:
        client = await self.assistant(chat_id)
        await client.play(chat_id, stream_for(link, video=bool(video)))

    async def seek_stream(self, chat_id: int, file_path: str, to_seek: int, duration: int, mode: str) -> None:
        client = await self.assistant(chat_id)
        await client.play(
            chat_id,
            stream_for(file_path, video=mode == "video", seek=f"-ss {to_seek} -to {duration}"),
        )

    async def stream_call(self, link: str) -> None:
        target = config.LOGGER_CHAT or 0
        client = await self.assistant(target)
        await client.play(target, MediaStream(link))
        await asyncio.sleep(0.2)
        await client.leave_call(target)

    async def join_call(
        self,
        chat_id: int,
        original_chat_id: int,
        link: str,
        video: bool | str | None = None,
    ) -> None:
        client = await self.assistant(chat_id)
        try:
            await client.play(chat_id, stream_for(link, video=bool(video)))
        except NoActiveGroupCall as exc:
            raise AssistantErr(get_text("voice.no_active_call")) from exc
        except TelegramServerError as exc:
            raise AssistantErr(get_text("voice.server_error")) from exc
        except (NotInCallError, NtgConnectionError) as exc:
            raise AssistantErr(get_text("voice.connect_failed")) from exc
        except Exception as exc:
            LOGGER.exception("Failed to join voice chat %s", chat_id)
            raise AssistantErr(str(exc)) from exc

        await add_active_chat(chat_id)
        await music_on(chat_id)
        if video:
            await add_active_video_chat(chat_id)
        if AUTO_LEAVING_ASSISTANT:
            self._autoend.pop(chat_id, None)

    async def speedup_stream(
        self, chat_id: int, file_path: str, speed: str, playing: list[QueueItem]
    ) -> None:
        async with self.lock(chat_id):
            await self._speedup_locked(chat_id, file_path, str(speed), playing)

    async def _speedup_locked(
        self, chat_id: int, file_path: str, speed: str, playing: list[QueueItem]
    ) -> None:
        client = await self.assistant(chat_id)
        if str(speed) == "1.0":
            return

        factor = SPEED_FACTORS.get(str(speed))
        if factor is None:
            raise ValueError(f"Unsupported playback speed: {speed}")

        chatdir = os.path.join("playback", str(speed))
        os.makedirs(chatdir, exist_ok=True)
        out = os.path.join(chatdir, os.path.basename(file_path))

        if not os.path.isfile(out):
            command = ["ffmpeg", "-y", "-i", str(file_path)]
            if playing[0].is_video:
                command.extend(["-filter:v", f"setpts={factor}*PTS"])
            command.extend(["-filter:a", f"atempo={speed}", out])
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg speed conversion failed: {stderr.decode(errors='replace')[-400:]}"
                )

        entry = playing[0]
        played = entry.played
        duration = entry.seconds
        seek = f"-ss {played} -to {duration}" if played else None

        await client.play(chat_id, stream_for(out, video=entry.is_video, seek=seek))

        current = db.get(chat_id) or []
        if not current or current[0].file != str(file_path):
            raise AssistantErr(get_text("voice.track_changed"))

        live = current[0]
        if not live.old_dur:
            live.old_dur = live.dur
            live.old_second = live.seconds
        live.played = played
        live.dur = str(duration)
        live.seconds = duration
        live.speed_path = out
        live.speed = float(speed)
        LOGGER.debug("Chat %s now playing at %sx (resumed at %ss)", chat_id, speed, played)
