from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from dataclasses import dataclass, field, fields
from typing import Any

SOURCE_MARKERS = ("live_", "vid_", "index_")


@dataclass(slots=True)
class Track:
    id: str
    title: str
    url: str
    duration: str = "00:00"
    duration_sec: int = 0
    channel_name: str | None = None
    album: str | None = None
    thumbnail: str | None = None
    view_count: str | None = None
    message_id: int = 0
    video: bool = False
    stream_mode: str = "balanced"
    user: str | None = None

    @property
    def is_live(self) -> bool:
        return self.duration_sec <= 0


@dataclass(slots=True)
class QueueItem(MutableMapping[str, Any]):
    title: str = "Unknown Title"
    file: str = ""
    vidid: str = ""
    dur: str = "00:00"
    streamtype: str = "audio"
    by: str = ""
    user_id: int = 0
    chat_id: int = 0
    seconds: int = 0
    played: int = 0
    speed: float = 1.0
    speed_path: str | None = None
    old_dur: str | None = None
    old_second: int | None = None
    autoplay: bool = False
    mystic: Any = None
    markup: str | None = None
    extra: dict[str, Any] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.title = str(self.title or "Unknown Title").title()
        self.file = str(self.file or "")
        self.vidid = str(self.vidid or "")
        self.dur = str(self.dur or "00:00")
        self.streamtype = str(self.streamtype or "audio")
        self.seconds = max(0, int(self.seconds or 0))
        self.played = max(0, int(self.played or 0))

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> QueueItem:
        known = {name for name in _FIELD_NAMES if name != "extra"}
        values = {key: value for key, value in data.items() if key in known}
        extra = {key: value for key, value in data.items() if key not in known}
        return cls(**values, extra=extra)

    @property
    def source(self) -> str:
        for marker in SOURCE_MARKERS:
            if marker in self.file:
                return marker.rstrip("_")
        return "file"

    @property
    def is_video(self) -> bool:
        return str(self.streamtype) == "video"

    @property
    def is_live(self) -> bool:
        return self.seconds <= 0

    @property
    def remaining(self) -> int:
        return max(0, self.seconds - self.played)

    @property
    def playable_target(self) -> str:
        if self.speed_path:
            return self.speed_path
        if self.source == "index":
            return self.vidid
        return self.file

    def reset_speed(self) -> None:
        if not self.old_dur:
            return
        self.dur = self.old_dur
        self.seconds = int(self.old_second or self.seconds)
        self.speed_path = None
        self.speed = 1.0

    def as_dict(self) -> dict[str, Any]:
        return dict(self)

    def __getitem__(self, key: str) -> Any:
        if key in _FIELD_NAMES:
            return getattr(self, key)
        return self.extra[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key in _FIELD_NAMES and key != "extra":
            setattr(self, key, value)
            return
        self.extra[key] = value

    def __delitem__(self, key: str) -> None:
        if key in _FIELD_NAMES and key != "extra":
            raise KeyError(f"Queue fields cannot be deleted: {key}")
        del self.extra[key]

    def __iter__(self) -> Iterator[str]:
        for name in _FIELD_NAMES:
            if name != "extra":
                yield name
        yield from self.extra

    def __len__(self) -> int:
        return len(_FIELD_NAMES) - 1 + len(self.extra)


_FIELD_NAMES: frozenset[str] = frozenset(item.name for item in fields(QueueItem))


class Queue:
    __slots__ = ("_chats",)

    def __init__(self) -> None:
        self._chats: dict[int, list[QueueItem]] = {}

    def __contains__(self, chat_id: object) -> bool:
        return chat_id in self._chats

    def __len__(self) -> int:
        return len(self._chats)

    def get(self, chat_id: int, default: Any = None) -> Any:
        if chat_id in self._chats:
            return self._chats[chat_id]
        return [] if default is None else default

    def setdefault(self, chat_id: int, default: Any = None) -> list[QueueItem]:
        return self._chats.setdefault(chat_id, default if default is not None else [])

    def __getitem__(self, chat_id: int) -> list[QueueItem]:
        return self._chats[chat_id]

    def __setitem__(self, chat_id: int, items: list[Any]) -> None:
        self._chats[chat_id] = [
            item if isinstance(item, QueueItem) else QueueItem.from_mapping(item)
            for item in items
        ]

    def __delitem__(self, chat_id: int) -> None:
        del self._chats[chat_id]

    def pop(self, chat_id: int, default: Any = None) -> Any:
        return self._chats.pop(chat_id, default)

    def clear(self) -> None:
        self._chats.clear()

    def items(self):
        return self._chats.items()

    def active_chats(self) -> list[int]:
        return [chat_id for chat_id, items in self._chats.items() if items]
