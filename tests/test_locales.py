from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from noxy.core.i18n import LANGUAGES, get_text

LOCALE_DIR = Path(__file__).resolve().parents[1] / "noxy" / "locales"
PLACEHOLDER = re.compile(r"{(\w+)}")


def _flatten(data: dict, prefix: str = "") -> dict[str, str]:
    flat: dict[str, str] = {}
    for key, value in data.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{path}."))
        elif isinstance(value, str):
            flat[path] = value
    return flat


def _locales() -> dict[str, dict[str, str]]:
    return {
        path.stem: _flatten(json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(LOCALE_DIR.glob("*.json"))
    }


def test_every_supported_language_has_a_locale_file():
    assert set(_locales()) == set(LANGUAGES)


def test_locales_share_the_same_keys():
    locales = _locales()
    reference = set(locales["en"])
    for language, strings in locales.items():
        assert reference - set(strings) == set(), language
        assert set(strings) - reference == set(), language


def test_placeholders_match_the_reference_locale():
    locales = _locales()
    reference = locales["en"]
    for language, strings in locales.items():
        for key, value in strings.items():
            expected = set(PLACEHOLDER.findall(reference[key]))
            found = set(PLACEHOLDER.findall(value))
            assert expected == found, f"{language}:{key}"


def test_locale_strings_do_not_contain_escaped_newlines():
    for language, strings in _locales().items():
        for key, value in strings.items():
            assert "\\n" not in value, f"{language}:{key}"


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_get_text_renders_known_keys(language: str):
    rendered = get_text("download.cancel", locale=language)
    assert rendered and rendered != "download.cancel"


def test_get_text_formats_values():
    assert "42" in get_text("download.done", elapsed="42", locale="en")


def test_get_text_returns_key_for_unknown_messages():
    assert get_text("does.not.exist") == "does.not.exist"


def test_get_text_falls_back_to_english():
    assert get_text("download.audio_name", locale="en")
    assert get_text("stream.live_track", locale="de")
