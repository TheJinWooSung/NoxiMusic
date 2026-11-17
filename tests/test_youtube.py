from __future__ import annotations

import pytest

from noxy.services.downloader import MODE_TUNING, DownloadMode, MediaDownloader
from noxy.services.track import Track
from noxy.services.youtube import YouTube


@pytest.fixture(scope="module")
def engine() -> YouTube:
    return YouTube(MediaDownloader(directory="/tmp/noximusic-test-downloads"))


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ?t=42", "dQw4w9WgXcQ"),
        ("https://music.youtube.com/watch?v=dQw4w9WgXcQ&list=RD", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
        ("not a video", None),
    ],
)
def test_extract_video_id(engine: YouTube, value, expected):
    assert engine.extract_video_id(value) == expected


def test_format_duration_handles_hours(engine: YouTube):
    assert engine.format_duration(75) == "01:15"
    assert engine.format_duration(3675) == "1:01:15"


@pytest.mark.parametrize(
    ("raw", "mode"),
    [("best", DownloadMode.BEST), ("PERFORMANCE", DownloadMode.PERFORMANCE), (None, DownloadMode.BALANCED)],
)
def test_download_mode_parsing(raw, mode):
    assert DownloadMode.parse(raw) is mode


def test_download_mode_falls_back_for_unknown_values():
    assert DownloadMode.parse("nonsense") is DownloadMode.BALANCED


def test_stable_key_keeps_video_ids(engine: YouTube):
    assert MediaDownloader.stable_key("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    hashed = MediaDownloader.stable_key("https://example.com/song.mp3")
    assert len(hashed) == 16
    assert hashed == MediaDownloader.stable_key("https://example.com/song.mp3")


def test_performance_mode_uses_more_fragments_than_best_mode():
    assert (
        MODE_TUNING[DownloadMode.PERFORMANCE]["concurrent_fragment_downloads"]
        > MODE_TUNING[DownloadMode.BEST]["concurrent_fragment_downloads"]
    )


def test_music_url_detection(engine: YouTube):
    assert engine.is_music_url("https://open.spotify.com/track/abc")
    assert engine.is_music_url("https://soundcloud.com/artist/song")
    assert not engine.is_music_url("https://example.com/song.mp3")


def test_related_scoring_prefers_same_artist(engine: YouTube):
    source = Track(id="a", title="Faded", url="u", channel_name="Alan Walker")
    same_artist = Track(id="b", title="Alone", url="u", channel_name="Alan Walker")
    other = Track(id="c", title="Alone", url="u", channel_name="Someone Else")
    assert engine._related_score(source, same_artist) > engine._related_score(source, other)


def test_same_track_detection(engine: YouTube):
    a = Track(id="x", title="Song - Artist", url="u", channel_name="Artist")
    b = Track(id="y", title="Song", url="u", channel_name="Artist")
    assert engine._is_same_track(a, b)
