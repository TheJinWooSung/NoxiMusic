from __future__ import annotations

import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import aiohttp

from noxy.config import COOKIES_URL

LOGGER = logging.getLogger(__name__)

COOKIES_DIR = Path(__file__).resolve().parents[1] / "cookies"
DEFAULT_COOKIE_FILE = COOKIES_DIR / "cookies.txt"
MAX_COOKIE_FILE_SIZE = 5 * 1024 * 1024
COOKIE_TAB_FIELDS = 7
ALLOWED_HOSTS = frozenset({"batbin.me"})


def normalise_cookie_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Cookie URLs must use HTTPS.")
    if parsed.hostname.lower() in ALLOWED_HOSTS:
        path = parsed.path.rstrip("/")
        if not path.startswith("/raw/"):
            name = path.rsplit("/", 1)[-1]
            if not name:
                raise ValueError("Invalid batbin cookie URL.")
            path = f"/raw/{name}"
        parsed = parsed._replace(path=path, query="", fragment="")
    return urlunparse(parsed)


def is_netscape_cookie_file(content: bytes) -> bool:
    if not content or b"\x00" in content:
        return False
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#HttpOnly_"):
            return len(line.split("\t")) >= COOKIE_TAB_FIELDS
        if line.startswith("#"):
            continue
        if len(line.split("\t")) >= COOKIE_TAB_FIELDS:
            return True
    return False


@dataclass(frozen=True, slots=True)
class CookieFile:
    path: Path
    size: int
    mtime: int

    @classmethod
    def probe(cls, path: Path) -> CookieFile | None:
        try:
            if not path.is_file():
                return None
            stat = path.stat()
            if not 0 < stat.st_size <= MAX_COOKIE_FILE_SIZE:
                return None
            if not is_netscape_cookie_file(path.read_bytes()):
                return None
            return cls(path=path, size=stat.st_size, mtime=stat.st_mtime_ns)
        except OSError:
            return None


class CookiesManager:
    def __init__(self) -> None:
        self.directory = COOKIES_DIR
        self._warned_missing = False
        self._signature: tuple[tuple[str, int, int], ...] | None = None
        self._selected: str | None = None

    @staticmethod
    def _urls() -> list[str]:
        return [str(value) for value in COOKIES_URL if value]

    async def refresh_if_changed(self) -> None:
        await self.initialize()

    def local_files(self) -> list[Path]:
        self.directory.mkdir(parents=True, exist_ok=True)
        cookies = [
            probe
            for probe in (CookieFile.probe(path) for path in self.directory.glob("*.txt"))
            if probe is not None
        ]
        return [cookie.path for cookie in cookies]

    def _signature_now(self) -> tuple[tuple[str, int, int], ...] | None:
        try:
            return tuple(
                sorted(
                    (path.name, path.stat().st_size, path.stat().st_mtime_ns)
                    for path in self.directory.glob("*.txt")
                    if path.is_file()
                )
            )
        except OSError:
            return None

    async def _download(
        self, session: aiohttp.ClientSession, url: str, destination: Path
    ) -> bool:
        try:
            target = normalise_cookie_url(url)
            async with session.get(target, allow_redirects=True) as response:
                response.raise_for_status()
                if response.url.scheme != "https":
                    raise ValueError("Cookie URL redirects must remain on HTTPS.")
                content = await response.content.read(MAX_COOKIE_FILE_SIZE + 1)
            if len(content) > MAX_COOKIE_FILE_SIZE:
                raise ValueError("Cookie file exceeds the 5 MiB limit.")
            if not is_netscape_cookie_file(content):
                raise ValueError("Downloaded content is not a valid Netscape cookie file.")
            temporary = destination.with_suffix(".tmp")
            temporary.write_bytes(content)
            os.chmod(temporary, 0o600)
            temporary.replace(destination)
        except (TimeoutError, aiohttp.ClientError, OSError, ValueError) as exc:
            LOGGER.warning("Could not load YouTube cookie entry: %s", exc)
            return False
        LOGGER.info("Loaded YouTube cookie file %s.", destination.name)
        return True

    async def initialize(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        urls = self._urls()
        if not urls:
            if not self.local_files():
                LOGGER.info("No YouTube cookies configured; public downloads will be attempted.")
            return

        timeout = aiohttp.ClientTimeout(total=25, connect=10)
        connector = aiohttp.TCPConnector(limit=4)
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            for index, url in enumerate(urls, start=1):
                destination = (
                    DEFAULT_COOKIE_FILE
                    if index == 1
                    else self.directory / f"cookies-{index}.txt"
                )
                await self._download(session, url, destination)

        if not self.local_files():
            LOGGER.warning("No valid YouTube cookie files found in %s.", self.directory)

    def get_cookie_file(self) -> str | None:
        signature = self._signature_now()
        if signature == self._signature:
            return self._selected

        files = self.local_files()
        if DEFAULT_COOKIE_FILE in files:
            selected: Path | None = DEFAULT_COOKIE_FILE
        else:
            selected = random.choice(files) if files else None

        self._signature = signature
        self._selected = str(selected) if selected else None

        if not selected and not self._warned_missing:
            self._warned_missing = True
            LOGGER.warning("YouTube cookies are missing; some downloads may fail.")
        return self._selected


cookies = CookiesManager()
