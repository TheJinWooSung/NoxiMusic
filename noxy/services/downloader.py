from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

import yt_dlp

if TYPE_CHECKING:
    from collections.abc import Callable

LOGGER = logging.getLogger(__name__)


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "no", "off", "n", ""}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def _env_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} is outside the supported range.")
    return value



def _env_size(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    if raw.isdigit():
        return int(raw)
    match = re.fullmatch(r"(\d+)\s*([kmg])\s*(?:i?b)?", raw, re.IGNORECASE)
    if not match:
        raise ValueError(f"{name} must be a byte count or use K, M or G suffixes.")
    power = {"k": 1, "m": 2, "g": 3}[match.group(2).lower()]
    return int(match.group(1)) * (1024 ** power)


DEFAULT_DOWNLOAD_MODE = os.getenv("DOWNLOAD_MODE", "balanced").strip().lower()
if DEFAULT_DOWNLOAD_MODE not in {"best", "balanced", "performance"}:
    raise ValueError("DOWNLOAD_MODE must be best, balanced or performance.")

YTDLP_CHUNK_SIZE = _env_size("YTDLP_CHUNK_SIZE", 10 * 1024 * 1024)
ARIA2C_ENABLED = _env_bool("ARIA2C_ENABLED", False)
ARIA2C_CONNECTIONS = _env_int("ARIA2C_CONNECTIONS", 16, maximum=64)
TG_AUDIO_FILESIZE_LIMIT = _env_size("TG_AUDIO_FILESIZE_LIMIT", 100 * 1024 * 1024)
TG_VIDEO_FILESIZE_LIMIT = _env_size("TG_VIDEO_FILESIZE_LIMIT", 4 * 1024 * 1024 * 1024)


PARTIAL_MARKERS = (".part", ".ytdl", ".temp", ".tmp")
VIDEO_ID_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
MAX_TRACKED_LOCKS = 512
CACHE_SWEEP_INTERVAL = 300.0


class DownloadMode(StrEnum):
    BEST = "best"
    BALANCED = "balanced"
    PERFORMANCE = "performance"

    @classmethod
    def parse(cls, value: str | DownloadMode | None) -> DownloadMode:
        if isinstance(value, cls):
            return value
        try:
            return cls(str(value or DEFAULT_DOWNLOAD_MODE).lower())
        except ValueError:
            return cls.BALANCED


@dataclass(frozen=True, slots=True)
class ModeProfile:
    concurrent_fragments: int
    retries: int
    fragment_retries: int
    file_access_retries: int
    max_height: int

    def as_options(self) -> dict[str, object]:
        return {
            "concurrent_fragment_downloads": self.concurrent_fragments,
            "retries": self.retries,
            "fragment_retries": self.fragment_retries,
            "file_access_retries": self.file_access_retries,
        }

    def as_legacy(self) -> dict[str, object]:
        return {**self.as_options(), "max_height": self.max_height}


_PROFILES: dict[DownloadMode, ModeProfile] = {
    DownloadMode.BEST: ModeProfile(6, 6, 6, 3, 1080),
    DownloadMode.BALANCED: ModeProfile(12, 4, 4, 3, 720),
    DownloadMode.PERFORMANCE: ModeProfile(16, 3, 3, 2, 480),
}

MODE_TUNING: dict[DownloadMode, dict[str, object]] = {
    mode: profile.as_legacy() for mode, profile in _PROFILES.items()
}

AUDIO_FORMAT = (
    "bestaudio[acodec=opus]/bestaudio[acodec=aac]/bestaudio[acodec=mp4a]/"
    "bestaudio/best"
)

VIDEO_FORMAT = (
    "best[height<={height}][ext=mp4]/"
    "bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
    "bestvideo[height<={height}]+bestaudio/best[height<={height}]"
)

DOWNLOAD_ERRORS: tuple[type[BaseException], ...] = (
    yt_dlp.utils.DownloadError,
    yt_dlp.utils.ExtractorError,
    yt_dlp.utils.PostProcessingError,
    OSError,
    TimeoutError,
)


class _SilentLogger:
    __slots__ = ()

    def debug(self, msg: str) -> None:
        return None

    info = debug
    warning = debug

    def error(self, msg: str) -> None:
        return None


@dataclass(slots=True, frozen=True)
class DownloadResult:
    path: str
    reused: bool = False
    attempts: int = 1

    def __bool__(self) -> bool:
        return bool(self.path)


def _is_complete(path: Path) -> bool:
    if not path.is_file():
        return False
    lowered = path.name.lower()
    if any(marker in lowered for marker in PARTIAL_MARKERS):
        return False
    try:
        size = path.stat().st_size
    except OSError:
        return False
    return size > 0


class MediaDownloader:
    def __init__(
        self,
        directory: str | Path = "downloads",
        *,
        max_parallel: int = 4,
        attempts: int = 3,
    ) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.attempts = max(1, int(attempts))
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()
        self._guard = asyncio.Lock()
        self._gate = asyncio.Semaphore(max(1, int(max_parallel)))
        self._last_sweep = 0.0
        self._cookie_provider: Callable[[], str | None] | None = None
        self._closed = False

        workers = max(4, min(16, (os.cpu_count() or 4) * 2))
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="noximusic-dl")
        self.aria2c = bool(ARIA2C_ENABLED and shutil.which("aria2c"))
        if ARIA2C_ENABLED and not self.aria2c:
            LOGGER.warning(
                "ARIA2C_ENABLED is set but aria2c is not on PATH; using native downloads."
            )

    def set_cookie_provider(self, provider: Callable[[], str | None]) -> None:
        self._cookie_provider = provider

    def _cookie_file(self) -> str | None:
        if self._cookie_provider is None:
            return None
        try:
            return self._cookie_provider()
        except Exception:
            LOGGER.debug("Cookie provider failed", exc_info=True)
            return None

    @staticmethod
    def _runtime_options() -> dict[str, object]:
        from noxy.helpers.dirs import DENO_PATH

        if not DENO_PATH:
            return {}
        return {"js_runtimes": {"deno": {"path": DENO_PATH}}}

    @staticmethod
    def stable_key(source: str) -> str:
        if len(source) == 11 and set(source) <= VIDEO_ID_ALPHABET:
            return source
        return hashlib.sha1(source.encode("utf-8")).hexdigest()[:16]

    async def _lock_for(self, key: str) -> asyncio.Lock:
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
                if len(self._locks) > MAX_TRACKED_LOCKS:
                    self._evict_locks()
                return lock
            self._locks.move_to_end(key)
            return lock

    def _evict_locks(self) -> None:
        for key in list(self._locks):
            if len(self._locks) <= MAX_TRACKED_LOCKS // 2:
                break
            lock = self._locks[key]
            if lock.locked():
                continue
            del self._locks[key]

    def _find_cached(self, prefix: str) -> str | None:
        try:
            candidates = [p for p in self.directory.glob(f"{prefix}*") if _is_complete(p)]
        except OSError:
            return None
        if not candidates:
            return None

        def _mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        return str(max(candidates, key=_mtime))

    def _sweep(self, *, max_age_seconds: float = 3 * 86_400) -> None:
        now = time.monotonic()
        if now - self._last_sweep < CACHE_SWEEP_INTERVAL:
            return
        self._last_sweep = now
        cutoff = time.time() - max_age_seconds
        removed = 0
        for entry in self.directory.glob("*"):
            try:
                if entry.is_file() and entry.stat().st_mtime < cutoff:
                    entry.unlink()
                    removed += 1
            except OSError:
                continue
        if removed:
            LOGGER.info("Pruned %d stale download(s) from %s", removed, self.directory)

    def _base_options(self, mode: DownloadMode, *, video: bool) -> dict[str, Any]:
        profile = _PROFILES[mode]
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _SilentLogger(),
            "noplaylist": True,
            "geo_bypass": True,
            "overwrites": False,
            "continuedl": True,
            "cachedir": False,
            "socket_timeout": 20,
            "extractor_retries": 2,
            "http_chunk_size": int(YTDLP_CHUNK_SIZE),
            "remote_components": ["ejs:npm"],
            "trim_file_name": 96,
            **profile.as_options(),
            **self._runtime_options(),
        }
        if cookie := self._cookie_file():
            options["cookiefile"] = cookie
        if self.aria2c:
            options.update(
                {
                    "external_downloader": "aria2c",
                    "external_downloader_args": [
                        f"-x{ARIA2C_CONNECTIONS}",
                        f"-s{ARIA2C_CONNECTIONS}",
                        "-k10M",
                        "--summary-interval=0",
                        "--console-log-level=warn",
                    ],
                }
            )
        if video:
            options.update(
                {
                    "format": VIDEO_FORMAT.format(height=profile.max_height),
                    "merge_output_format": "mp4",
                }
            )
        else:
            options["format"] = AUDIO_FORMAT
        return options

    def _run_download(
        self,
        source: str,
        *,
        prefix: str,
        mode: DownloadMode,
        video: bool,
        key: str,
    ) -> str | None:
        options = self._base_options(mode, video=video)
        options["outtmpl"] = str(self.directory / f"{prefix}%(ext)s")
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(source, download=True)
                cached = self._find_cached(prefix)
                if cached:
                    return cached
                if not info:
                    return None
                prepared = Path(ydl.prepare_filename(info))
                return str(prepared) if _is_complete(prepared) else None
        except DOWNLOAD_ERRORS as exc:
            LOGGER.warning("Download failed for %s: %s", key, exc)
        except Exception:
            LOGGER.exception("Unexpected download failure for %s", key)
        return None

    async def _with_retries(
        self,
        source: str,
        *,
        prefix: str,
        mode: DownloadMode,
        video: bool,
        key: str,
    ) -> DownloadResult | None:
        loop = asyncio.get_running_loop()
        for attempt in range(1, self.attempts + 1):
            path = await loop.run_in_executor(
                self._executor,
                lambda: self._run_download(
                    source, prefix=prefix, mode=mode, video=video, key=key
                ),
            )
            if path:
                if not self._fits_limits(path, video=video):
                    LOGGER.warning(
                        "Downloaded file for %s exceeds the Telegram size limit.", key
                    )
                    Path(path).unlink(missing_ok=True)
                    return None
                return DownloadResult(path=path, attempts=attempt)
            if attempt < self.attempts:
                delay = min(8.0, float(2 ** (attempt - 1)))
                LOGGER.info(
                    "Retrying download for %s in %.1fs (attempt %d/%d)",
                    key,
                    delay,
                    attempt + 1,
                    self.attempts,
                )
                await asyncio.sleep(delay)
        return None

    async def download_result(
        self,
        source: str,
        *,
        video: bool = False,
        mode: DownloadMode | str = DownloadMode.BALANCED,
        key: str | None = None,
    ) -> DownloadResult | None:
        if not source or self._closed:
            return None

        mode_enum = DownloadMode.parse(mode)
        kind = "video" if video else "audio"
        resolved_key = key or self.stable_key(source)
        prefix = f"{resolved_key}.{mode_enum.value}.{kind}."
        lock = await self._lock_for(f"{resolved_key}:{mode_enum.value}:{kind}")

        async with lock:
            cached = self._find_cached(prefix)
            if cached:
                return DownloadResult(path=cached, reused=True, attempts=0)
            async with self._gate:
                self._sweep()
                return await self._with_retries(
                    source, prefix=prefix, mode=mode_enum, video=video, key=resolved_key
                )

    async def download(
        self,
        source: str,
        *,
        video: bool = False,
        mode: DownloadMode | str = DownloadMode.BALANCED,
        key: str | None = None,
    ) -> str | None:
        result = await self.download_result(source, video=video, mode=mode, key=key)
        return result.path if result else None

    async def extract_info(self, url: str, *, flat: bool = False) -> dict | None:
        def _run() -> dict | None:
            options: dict[str, Any] = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "socket_timeout": 15,
                "retries": 2,
                "extractor_retries": 2,
                "noplaylist": not flat,
                "extract_flat": "in_playlist" if flat else False,
                "remote_components": ["ejs:npm"],
                **self._runtime_options(),
            }
            if cookie := self._cookie_file():
                options["cookiefile"] = cookie
            try:
                with yt_dlp.YoutubeDL(options) as ydl:
                    return ydl.extract_info(url, download=False)
            except Exception as exc:
                LOGGER.warning("Metadata extraction failed for %s: %s", url, exc)
                return None

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, _run)

    async def direct_url(self, source: str, *, audio: bool = True) -> tuple[int, str | None]:
        info = await self.extract_info(source)
        if not info:
            return 0, None

        formats = [item for item in (info.get("formats") or []) if isinstance(item, dict)]
        usable = [item for item in formats if item.get("url")]
        if not usable:
            return 0, info.get("url")

        if audio:
            pool = [
                item
                for item in usable
                if item.get("vcodec") in (None, "none")
                and "m3u8" not in str(item.get("protocol") or "").lower()
            ] or usable
            pool.sort(key=lambda item: item.get("abr") or 0, reverse=True)
        else:
            pool = [
                item for item in usable if item.get("vcodec") not in (None, "none")
            ] or usable
            pool.sort(key=lambda item: (item.get("height") or 0, item.get("tbr") or 0))

        return 1, pool[0].get("url")

    @staticmethod
    def _fits_limits(path: str, *, video: bool) -> bool:
        limit = TG_VIDEO_FILESIZE_LIMIT if video else TG_AUDIO_FILESIZE_LIMIT
        try:
            return Path(path).stat().st_size <= limit
        except OSError:
            return False

    def is_stream_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        return path.endswith((".m3u8", ".mpd", ".mp3", ".aac", ".flac", ".wav", ".ogg"))

    async def shutdown(self) -> None:
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._locks.clear()
