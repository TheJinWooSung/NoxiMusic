from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from functools import cache
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger(__name__)

LOCALE_DIR = Path(__file__).resolve().parents[1] / "locales"
DEFAULT_LANGUAGE = "en"

LANGUAGES = {
    "en": "English",
    "ar": "العربية",
    "de": "Deutsch",
    "es": "Español",
    "fa": "فارسی",
    "fr": "Français",
    "hi": "हिन्दी",
    "id": "Bahasa Indonesia",
    "it": "Italiano",
    "pt": "Português",
    "ru": "Русский",
    "tr": "Türkçe",
    "uz": "O‘zbekcha",
}

_CURRENT_LANGUAGE: ContextVar[str] = ContextVar("noxy_language", default=DEFAULT_LANGUAGE)

Locale = dict[str, Any]


@cache
def _load_locale(language: str = DEFAULT_LANGUAGE) -> Locale:
    resolved = language if language in LANGUAGES else DEFAULT_LANGUAGE
    path = LOCALE_DIR / f"{resolved}.json"
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        LOGGER.exception("Unable to load locale file %s", path)
        return {} if resolved == DEFAULT_LANGUAGE else _load_locale(DEFAULT_LANGUAGE)
    if not isinstance(data, dict):
        LOGGER.error("Locale root must be a JSON object: %s", path)
        return {} if resolved == DEFAULT_LANGUAGE else _load_locale(DEFAULT_LANGUAGE)
    return data


def _resolve(data: Locale, parts: list[str]) -> Any:
    value: Any = data
    for part in parts:
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def set_current_language(language: str) -> None:
    _CURRENT_LANGUAGE.set(language if language in LANGUAGES else DEFAULT_LANGUAGE)


def get_current_language() -> str:
    return _CURRENT_LANGUAGE.get()


def get_languages() -> dict[str, str]:
    return LANGUAGES.copy()


def get_locale(key: str, locale: str | None = None) -> Any:
    language = locale or get_current_language()
    parts = key.split(".")
    value = _resolve(_load_locale(language), parts)
    if value is None and language != DEFAULT_LANGUAGE:
        value = _resolve(_load_locale(DEFAULT_LANGUAGE), parts)
    if value is None:
        LOGGER.warning("Missing locale key: %s", key)
    return value


def get_text(key: str, locale: str | None = None, **values: Any) -> str:
    value = get_locale(key, locale)
    if not isinstance(value, str):
        LOGGER.warning("Locale value is not a string: %s", key)
        return key
    if not values:
        return value
    try:
        return value.format(**values)
    except (KeyError, IndexError, ValueError):
        LOGGER.exception("Unable to format locale string: %s", key)
        return value
