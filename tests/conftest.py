from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config: pytest.Config) -> None:
    os.environ.setdefault("API_ID", "12345")
    os.environ.setdefault("API_HASH", "0123456789abcdef0123456789abcdef")
    os.environ.setdefault("BOT_TOKEN", "12345:AAFakeTokenForTests")
    os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
    os.environ.setdefault("OWNER_ID", "1")

    stubs = Path("/tmp/noximusic-test-bin")
    stubs.mkdir(exist_ok=True)
    for binary in ("ffmpeg", "ffprobe"):
        path = stubs / binary
        if not path.exists():
            path.write_text("#!/bin/sh\nexit 0\n")
            path.chmod(0o755)
    os.environ["PATH"] = f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}"


@pytest.fixture()
def clean_cache():
    from noxy.database import (
        active_chats,
        active_video_chats,
        assistant_map,
        autoplay_map,
        loop_map,
        nonadmin_map,
        paused_map,
        playmode_map,
        playtype_map,
    )

    caches = (
        active_chats,
        active_video_chats,
        assistant_map,
        autoplay_map,
        loop_map,
        nonadmin_map,
        paused_map,
        playmode_map,
        playtype_map,
    )
    for cache in caches:
        cache.clear()
    yield
    for cache in caches:
        cache.clear()
