from __future__ import annotations

import logging
import os
from typing import Any

from noxy.core.state import autoclean

LOGGER = logging.getLogger(__name__)

EPHEMERAL_MARKERS = ("vid_", "live_", "index_")


def _path_of(popped: Any) -> str | None:
    value = popped.get("file") if isinstance(popped, dict) else getattr(popped, "file", None)
    if not value:
        return None
    try:
        return os.fsdecode(os.fspath(value))
    except (TypeError, ValueError):
        return None


async def auto_clean(popped: Any) -> None:
    target = _path_of(popped)
    if target is None:
        LOGGER.debug("Skipping cleanup for an invalid queue entry")
        return

    for index in range(len(autoclean) - 1, -1, -1):
        if autoclean[index] == target:
            autoclean.pop(index)
            break

    if any(marker in target for marker in EPHEMERAL_MARKERS):
        return
    if target in autoclean:
        return

    try:
        if os.path.isfile(target):
            os.remove(target)
    except OSError:
        LOGGER.warning("Could not remove temporary playback file %s", target, exc_info=True)
