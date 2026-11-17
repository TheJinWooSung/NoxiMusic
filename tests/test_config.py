from __future__ import annotations

import pytest

from noxy.config import Config

BASE_ENV = {
    "API_ID": "123",
    "API_HASH": "abc",
    "BOT_TOKEN": "555:secret",
    "MONGO_URI": "mongodb://localhost:27017",
}


def _config(monkeypatch, tmp_path, **overrides) -> Config:
    monkeypatch.chdir(tmp_path)
    keys = (
        "API_ID",
        "API_HASH",
        "BOT_TOKEN",
        "OWNER_ID",
        "LOGGER_ID",
        "MONGO_URI",
        "STRING1",
        "STRING2",
        "STRING3",
        "STRING4",
        "STRING5",
        "COOKIES_URL",
        "SUPPORT_CHANNEL",
        "SUPPORT_CHAT",
    )
    for key in keys:
        monkeypatch.delenv(key, raising=False)
    for key, value in {**BASE_ENV, **overrides}.items():
        monkeypatch.setenv(key, str(value))
    return Config()


def test_required_values_and_optional_defaults(monkeypatch, tmp_path):
    config = _config(monkeypatch, tmp_path)
    assert config.API_ID == 123
    assert config.BOT_TOKEN == "555:secret"
    assert config.OWNER_ID == 0
    assert config.LOGGER_CHAT is None
    assert config.SESSION_STRINGS == ()
    assert config.COOKIES_URL == []
    assert config.SUPPORT_CHAT.startswith("https://")
    assert config.SUPPORT_CHANNEL.startswith("https://")


def test_session_slots_are_preserved(monkeypatch, tmp_path):
    config = _config(monkeypatch, tmp_path, STRING1="first", STRING3="third")
    assert config.SESSION_STRINGS == ((1, "first"), (3, "third"))


def test_cookie_urls_accept_comma_and_space_separated_values(monkeypatch, tmp_path):
    config = _config(
        monkeypatch,
        tmp_path,
        COOKIES_URL="https://a.example/c.txt, https://b.example/c.txt",
    )
    assert config.COOKIES_URL == [
        "https://a.example/c.txt",
        "https://b.example/c.txt",
    ]


def test_logger_chat_parses_numeric_chat_ids(monkeypatch, tmp_path):
    config = _config(monkeypatch, tmp_path, LOGGER_ID="-1001234567890")
    assert config.LOGGER_CHAT == -1001234567890


def test_env_file_does_not_override_process_environment(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "API_ID=123\nAPI_HASH=file-hash\nBOT_TOKEN=555:secret\n"
        "MONGO_URI=mongodb://localhost:27017\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("API_ID", "456")
    monkeypatch.setenv("API_HASH", "process-hash")
    monkeypatch.setenv("BOT_TOKEN", "555:secret")
    monkeypatch.setenv("MONGO_URI", "mongodb://localhost:27017")
    config = Config()
    assert config.API_ID == 456
    assert config.API_HASH == "process-hash"


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("API_ID", "invalid", "API_ID"),
        ("BOT_TOKEN", "invalid", "BOT_TOKEN"),
        ("MONGO_URI", "https://example.com", "MONGO_URI"),
    ],
)
def test_invalid_required_values_are_rejected(monkeypatch, tmp_path, key, value, message):
    with pytest.raises(ValueError, match=message):
        _config(monkeypatch, tmp_path, **{key: value})
