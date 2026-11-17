import asyncio
import json
import math
import subprocess
from functools import reduce
from pathlib import Path
from typing import Any, Final


def get_readable_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} day{'s' if days != 1 else ''}")
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if minutes:
        parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
    if seconds or not parts:
        parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
    return ", ".join(parts)


def convert_bytes(size: float) -> str:
    if size <= 0:
        return "0 B"

    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024
    return f"{value:.2f} PiB"


async def int_to_alpha(user_id: int) -> str:
    return "".join(chr(ord("a") + int(digit)) for digit in str(user_id))


async def alpha_to_int(user_id_alphabet: str) -> int:
    if not user_id_alphabet or any(
        char < "a" or char > "j" for char in user_id_alphabet
    ):
        raise ValueError("Encoded ID must contain only letters a through j.")
    return int("".join(str(ord(char) - ord("a")) for char in user_id_alphabet))


def time_to_seconds(value: str | int) -> int:
    parts = str(value).strip().split(":")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"Invalid time value: {value!r}.")
    return reduce(lambda total, part: total * 60 + int(part), parts, 0)


def _format_duration(seconds: int) -> str:
    seconds = max(0, int(seconds))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days:02d}:{hours:02d}:{minutes:02d}:{seconds:02d}"
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def seconds_to_min(seconds: int | float | str | None) -> str:
    if seconds is None:
        return "-"
    try:
        return _format_duration(int(float(seconds)))
    except (TypeError, ValueError, OverflowError):
        return "-"


def speed_converter(seconds: int | float | None, speed: float | str):
    if seconds is None:
        return "-", 0

    try:
        elapsed = max(0.0, float(seconds))
        rate = float(speed)
    except (TypeError, ValueError):
        raise ValueError("Playback duration and speed must be numeric.") from None

    if not math.isfinite(rate) or rate <= 0:
        raise ValueError("Playback speed must be a positive finite number.")

    converted_seconds = elapsed / rate
    return _format_duration(int(converted_seconds)), converted_seconds


async def check_duration(file_path: str | Path) -> float:
    return await asyncio.to_thread(_probe_duration, file_path)


def _probe_duration(file_path: str | Path) -> float:
    command = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=duration",
        "-of",
        "json",
        str(file_path),
    ]
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
        metadata: dict[str, Any] = json.loads(result.stdout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"ffprobe timed out for {file_path}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise RuntimeError(f"ffprobe failed for {file_path}: {detail}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"ffprobe returned invalid metadata for {file_path}") from exc

    duration = (metadata.get("format") or {}).get("duration")
    if duration is None:
        duration = next(
            (
                stream.get("duration")
                for stream in metadata.get("streams", [])
                if stream.get("duration") not in (None, "N/A")
            ),
            None,
        )
    try:
        value = float(duration)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"No media duration found for {file_path}") from exc

    if not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid media duration for {file_path}: {value!r}")
    return value

VIDEO_EXTENSIONS: Final[frozenset[str]] = frozenset(
    {
        "webm", "mkv", "flv", "vob", "ogv", "ogg", "rrc", "gifv", "mng",
        "mov", "avi", "qt", "wmv", "yuv", "rm", "asf", "amv", "mp4", "m4p",
        "m4v", "mpg", "mp2", "mpeg", "mpe", "mpv", "svi", "3gp", "3g2",
        "mxf", "roq", "nsv", "f4v", "f4p", "f4a", "f4b",
    }
)

formats: tuple[str, ...] = tuple(sorted(VIDEO_EXTENSIONS))

FFPROBE_TIMEOUT_SECONDS = 20
