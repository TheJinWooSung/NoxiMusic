from __future__ import annotations

from noxy import db
from noxy.core.state import autoclean
from noxy.helpers.formatting import check_duration, seconds_to_min, time_to_seconds
from noxy.services.track import QueueItem

URL_STREAM_HOST = "20.212.146.162"


async def _insert_queue(
    chat_id: int,
    item: QueueItem,
    file: str,
    forceplay: bool | str | None = False,
    track_cleanup: bool = False,
    max_size: int | None = None,
) -> bool:
    from noxy.core.call import noxy

    lock = noxy.lock(chat_id)
    async with lock:
        queue = db.setdefault(chat_id, [])
        if max_size is not None and not forceplay and len(queue) >= max_size:
            return False
        if forceplay:
            queue.insert(0, item)
        else:
            queue.append(item)
        if track_cleanup:
            autoclean.append(file)
        return True


async def put_queue(
    chat_id: int,
    original_chat_id: int,
    file: str,
    title: str,
    duration: str,
    user: str,
    vidid: str,
    user_id: int,
    stream: str,
    forceplay: bool | str | None = None,
    max_size: int | None = None,
) -> bool:
    try:
        seconds = time_to_seconds(duration) - 3
    except ValueError:
        seconds = 0
    item = QueueItem(
        title=title,
        file=file,
        vidid=vidid,
        dur=duration,
        streamtype=stream,
        by=user,
        user_id=user_id,
        chat_id=original_chat_id,
        seconds=seconds,
    )
    return await _insert_queue(
        chat_id, item, file, forceplay, track_cleanup=True, max_size=max_size
    )


async def put_queue_index(
    chat_id: int,
    original_chat_id: int,
    file: str,
    title: str,
    duration: str,
    user: str,
    vidid: str,
    stream: str,
    forceplay: bool | str | None = None,
    max_size: int | None = None,
) -> bool:
    seconds = 0
    if URL_STREAM_HOST in vidid:
        try:
            seconds = int(await check_duration(vidid))
            duration = seconds_to_min(seconds)
        except (OSError, RuntimeError, ValueError):
            duration = "URL Stream"
            seconds = 0

    item = QueueItem(
        title=title,
        file=file,
        vidid=vidid,
        dur=duration,
        streamtype=stream,
        by=user,
        chat_id=original_chat_id,
        seconds=seconds,
    )
    return await _insert_queue(chat_id, item, file, forceplay, max_size=max_size)
