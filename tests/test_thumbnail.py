from __future__ import annotations

import pytest

from noxy.helpers.thumbnail import _video_id


@pytest.mark.parametrize(
    "url",
    [
        "https://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://music.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
    ],
)
def test_video_id_accepts_youtube_hosts(url: str):
    assert _video_id(url) == "dQw4w9WgXcQ"


@pytest.mark.parametrize(
    "url",
    [
        "https://evil-youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com.evil.test/watch?v=dQw4w9WgXcQ",
        "https://evil-youtu.be/dQw4w9WgXcQ",
        "https://example.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_video_id_rejects_non_youtube_hosts(url: str):
    assert _video_id(url) is None


def test_video_id_accepts_plain_id():
    assert _video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
