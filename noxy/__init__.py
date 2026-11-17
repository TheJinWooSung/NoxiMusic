from __future__ import annotations

import time

from noxy import config
from noxy.core.assistants import AssistantManager
from noxy.core.bot import MikoBot
from noxy.helpers.dirs import ensure_runtime_dirs
from noxy.services.downloader import MediaDownloader
from noxy.services.track import Queue
from noxy.services.youtube import YouTube as YouTubeEngine

_boot_ = time.time()

db: Queue = Queue()

ensure_runtime_dirs()

app = MikoBot()
userbot = AssistantManager()

downloader = MediaDownloader()
from noxy.services.cookies import cookies

downloader.set_cookie_provider(cookies.get_cookie_file)

from noxy.services.providers import (
    AppleAPI,
    RessoAPI,
    SoundAPI,
    SpotifyAPI,
)
from noxy.services.telegram import TeleAPI

YouTube = YouTubeEngine(downloader)
Apple = AppleAPI(YouTube)
SoundCloud = SoundAPI(YouTube)
Spotify = SpotifyAPI(YouTube)
Resso = RessoAPI(YouTube)
Telegram = TeleAPI()

__all__ = [
    "Apple",
    "AssistantManager",
    "MikoBot",
    "Queue",
    "Resso",
    "SoundCloud",
    "Spotify",
    "Telegram",
    "YouTube",
    "_boot_",
    "app",
    "config",
    "db",
    "downloader",
    "userbot",
]
