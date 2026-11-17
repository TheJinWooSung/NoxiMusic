from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

LOGGER = logging.getLogger(__name__)


def _load_env_file(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        LOGGER.warning("Could not read environment file: %s", path)
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value)


def _integer(name: str, default: int = 0) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc


def _chat_id(value: str) -> int | str | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return value


class Config:
    def __init__(self) -> None:
        _load_env_file()
        self.API_ID = _integer("API_ID")
        self.API_HASH = os.getenv("API_HASH", "").strip()
        self.BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
        self.OWNER_ID = _integer("OWNER_ID")
        self.LOGGER_ID = os.getenv("LOGGER_ID", "").strip()
        self.LOGGER_CHAT = _chat_id(self.LOGGER_ID)
        self.MONGO_URI = os.getenv("MONGO_URI", "").strip()
        self.SESSION_STRINGS = tuple(
            (slot, value)
            for slot in range(1, 6)
            if (value := os.getenv(f"STRING{slot}", "").strip())
        )
        self.COOKIES_URL = [
            value
            for value in re.split(r"[,\s]+", os.getenv("COOKIES_URL", "").strip())
            if value
        ]
        self.SUPPORT_CHANNEL = os.getenv(
            "SUPPORT_CHANNEL", "https://t.me/ErenBots"
        ).strip().rstrip("/")
        self.SUPPORT_CHAT = os.getenv(
            "SUPPORT_CHAT", "https://t.me/RadhaSprt"
        ).strip().rstrip("/")
        self._validate()

    def _validate(self) -> None:
        if self.API_ID <= 0 or not self.API_HASH:
            raise ValueError("API_ID and API_HASH are required.")
        if not self.BOT_TOKEN or ":" not in self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required and must be a valid bot token.")
        if not self.MONGO_URI:
            raise ValueError("MONGO_URI is required.")
        parts = urlsplit(self.MONGO_URI)
        if parts.scheme not in {"mongodb", "mongodb+srv"} or not parts.hostname:
            raise ValueError("MONGO_URI must be a valid MongoDB connection URL.")


CONFIG = Config()
API_ID = CONFIG.API_ID
API_HASH = CONFIG.API_HASH
BOT_TOKEN = CONFIG.BOT_TOKEN
OWNER_ID = CONFIG.OWNER_ID
LOGGER_ID = CONFIG.LOGGER_ID
LOGGER_CHAT = CONFIG.LOGGER_CHAT
MONGO_URI = CONFIG.MONGO_URI
SESSION_STRINGS = CONFIG.SESSION_STRINGS
COOKIES_URL = CONFIG.COOKIES_URL
SUPPORT_CHANNEL = CONFIG.SUPPORT_CHANNEL
SUPPORT_CHAT = CONFIG.SUPPORT_CHAT
