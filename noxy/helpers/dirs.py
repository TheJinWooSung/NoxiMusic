from __future__ import annotations

import logging
import shutil
from pathlib import Path

LOGGER = logging.getLogger(__name__)

FFMPEG_PATH = shutil.which("ffmpeg")
FFPROBE_PATH = shutil.which("ffprobe")
DENO_PATH = shutil.which("deno")
ARIA2C_PATH = shutil.which("aria2c")

RUNTIME_DIRS = (
    "cache",
    "downloads",
    "playback",
    "noxy/cookies",
)


def ensure_runtime_dirs() -> None:
    missing = [
        name
        for name, path in (("FFmpeg", FFMPEG_PATH), ("FFprobe", FFPROBE_PATH))
        if not path
    ]
    if missing:
        raise RuntimeError(
            "Required runtime executable(s) missing from PATH: "
            + ", ".join(missing)
            + ". Install FFmpeg (which ships ffprobe) before starting NoxiMusic."
        )

    for directory in RUNTIME_DIRS:
        Path(directory).mkdir(parents=True, exist_ok=True)

    LOGGER.debug("Runtime directories ready (ffmpeg=%s)", FFMPEG_PATH)
    if DENO_PATH:
        LOGGER.debug("Deno JavaScript runtime: %s", DENO_PATH)
    else:
        LOGGER.warning(
            "Deno was not found on PATH; yt-dlp may fall back to slower formats. "
            "Install Deno to unlock the fast download path."
        )
    if ARIA2C_PATH:
        LOGGER.info("aria2c detected: parallel downloads available (%s).", ARIA2C_PATH)


def cleanup_temp_dir(directory: str = "cache", *, max_age_seconds: int = 86_400) -> int:
    import time

    path = Path(directory)
    if not path.is_dir():
        return 0
    cutoff = time.time() - max_age_seconds
    removed = 0
    for entry in path.iterdir():
        try:
            if entry.is_file() and entry.stat().st_mtime < cutoff:
                entry.unlink()
                removed += 1
        except OSError:
            continue
    return removed

dirr = ensure_runtime_dirs

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ensure_runtime_dirs()
