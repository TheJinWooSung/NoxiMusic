from __future__ import annotations

import logging
from typing import Any

import aiohttp

LOGGER = logging.getLogger(__name__)

BASE_URL = "https://batbin.me/"
TIMEOUT = aiohttp.ClientTimeout(total=20)


async def post(url: str, *args: Any, **kwargs: Any) -> Any:
    async with (
        aiohttp.ClientSession(timeout=TIMEOUT) as session,
        session.post(url, *args, **kwargs) as response,
    ):
        response.raise_for_status()
        try:
            return await response.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            return await response.text()


async def paste(content: str) -> str | None:
    try:
        response = await post(f"{BASE_URL}api/v2/paste", data=content)
    except (TimeoutError, aiohttp.ClientError):
        LOGGER.debug("Paste upload failed", exc_info=True)
        return None

    if not isinstance(response, dict) or not response.get("success"):
        return None
    paste_id = response.get("message")
    if not isinstance(paste_id, str) or not paste_id.strip():
        return None
    return f"{BASE_URL}{paste_id.strip().lstrip('/')}"
