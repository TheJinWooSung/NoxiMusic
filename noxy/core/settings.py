from __future__ import annotations

import os


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "no", "off", "n", ""}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def _integer(name: str, default: int, minimum: int = 0, maximum: int | None = None) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    if value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum or 'unlimited'}.")
    return value


AUTO_LEAVING_ASSISTANT = _boolean("AUTO_LEAVING_ASSISTANT", False)
PREFETCH_ENABLED = _boolean("PREFETCH_ENABLED", True)
PREFETCH_COUNT = _integer("PREFETCH_COUNT", 1, maximum=3)
