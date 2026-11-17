from __future__ import annotations

from typing import Any

from pytgcalls.types import AudioQuality, MediaStream, VideoQuality

SPEED_FACTORS = {"0.5": 2.0, "0.75": 4 / 3, "1.5": 2 / 3, "2.0": 0.5}


class Unplayable(Exception):
    def __init__(self, source: str) -> None:
        super().__init__(f"Source could not be prepared: {source}")
        self.source = source


def stream_for(path: str, *, video: bool, seek: str | None = None) -> MediaStream:
    kwargs: dict[str, Any] = {"audio_parameters": AudioQuality.HIGH}
    if video:
        kwargs["video_parameters"] = VideoQuality.HD_720p
    if seek:
        kwargs["ffmpeg_parameters"] = seek
    return MediaStream(path, **kwargs)
