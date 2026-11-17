from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from dataclasses import replace
from typing import TypedDict
from urllib.parse import parse_qs, urlparse

import aiohttp

from noxy.core.limits import PLAYLIST_FETCH_LIMIT
from noxy.helpers.formatting import time_to_seconds
from noxy.services.cache import TTLCache
from noxy.services.downloader import DownloadMode, MediaDownloader
from noxy.services.track import Track

LOGGER = logging.getLogger(__name__)
HTTP_TIMEOUT = max(1, int(os.getenv("HTTP_TIMEOUT", "10")))

try:
    from py_yt import Playlist as YtPlaylist
    from py_yt import VideosSearch
except ImportError:
    VideosSearch = None
    YtPlaylist = None
    LOGGER.error("py-yt-search is not installed; YouTube search will be unavailable.")

_VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
_WATCH_RE = re.compile(
    r"(https?://)?(www\.|m\.|music\.)?"
    r"(youtube\.com/(watch\?v=|shorts/|playlist\?list=)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11}|PL[A-Za-z0-9_-]+)([&?][^\s]*)?"
)

MUSIC_DOMAINS = frozenset(
    {
        "soundcloud.com",
        "on.soundcloud.com",
        "music.apple.com",
        "geo.music.apple.com",
        "deezer.com",
        "tidal.com",
        "listen.tidal.com",
        "bandcamp.com",
        "spotify.com",
        "open.spotify.com",
        "jiosaavn.com",
        "saavn.com",
    }
)


class TrackDetails(TypedDict):
    title: str
    link: str
    vidid: str
    duration_min: str
    duration_sec: int


class YouTube:
    base = "https://www.youtube.com/watch?v="

    def __init__(self, downloader: MediaDownloader | None = None) -> None:
        self.downloader = downloader or MediaDownloader()
        self._search_cache: TTLCache[tuple, Track] = TTLCache(ttl=600, max_entries=800)
        self._multi_cache: TTLCache[tuple, list[Track]] = TTLCache(ttl=600, max_entries=300)
        self._info_cache: TTLCache[str, dict] = TTLCache(ttl=300, max_entries=400)
        self._flat_cache: TTLCache[str, dict] = TTLCache(ttl=300, max_entries=200)
        self._http: aiohttp.ClientSession | None = None

    @staticmethod
    def normalize_mode(mode: str | None) -> DownloadMode:
        return DownloadMode.parse(mode)

    @staticmethod
    def trim_title(title: str | None, limit: int = 80) -> str | None:
        return title[:limit] if title else title

    @staticmethod
    def format_duration(seconds: int) -> str:
        minutes, secs = divmod(max(int(seconds), 0), 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"

    @staticmethod
    def _session_kwargs() -> dict:
        return {
            "timeout": aiohttp.ClientTimeout(total=HTTP_TIMEOUT, connect=5),
            "connector": aiohttp.TCPConnector(limit=32, ttl_dns_cache=300),
        }

    async def _client(self) -> aiohttp.ClientSession:
        if self._http is None or self._http.closed:
            self._http = aiohttp.ClientSession(**self._session_kwargs())
        return self._http

    def extract_video_id(self, value: str | None) -> str | None:
        if not value:
            return None
        value = value.strip()
        if _VIDEO_ID_RE.fullmatch(value):
            return value

        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        path = parsed.path.strip("/")

        if host == "youtu.be" or host.endswith(".youtu.be"):
            candidate = path.split("/")[0] if path else ""
            return candidate if _VIDEO_ID_RE.fullmatch(candidate) else None

        if host == "youtube.com" or host.endswith(".youtube.com"):
            if path == "watch":
                candidate = (parse_qs(parsed.query).get("v") or [None])[0]
                return candidate if candidate and _VIDEO_ID_RE.fullmatch(candidate) else None
            if path.startswith(("shorts/", "embed/", "live/")):
                candidate = path.split("/")[1]
                return candidate if _VIDEO_ID_RE.fullmatch(candidate) else None
        return None

    def valid(self, url: str) -> bool:
        return bool(_WATCH_RE.match(url))

    def is_music_url(self, url: str) -> bool:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith(f".{d}") for d in MUSIC_DOMAINS)

    def is_stream_url(self, url: str) -> bool:
        return self.downloader.is_stream_url(url)

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        parsed = urlparse(value)
        return bool(parsed.scheme in {"http", "https"} and parsed.netloc)

    async def _search_raw(self, query: str, limit: int) -> list[dict]:
        if VideosSearch is None:
            return []
        try:
            search = VideosSearch(query, limit=max(1, limit), with_live=False, max_retries=1)
            return list((await search.next()).get("result") or [])
        except Exception as exc:
            LOGGER.warning("YouTube search failed for %r: %s", query, exc)
            return []

    def _build_track(
        self,
        *,
        data: dict,
        m_id: int = 0,
        video: bool = False,
        mode: str = "balanced",
        fallback_url: str | None = None,
    ) -> Track | None:
        track_id = data.get("id") or self.extract_video_id(data.get("url") or fallback_url)
        if not track_id:
            return None

        thumbnails = data.get("thumbnails") or []
        thumbnail = None
        if thumbnails:
            thumb = thumbnails[-1]
            thumbnail = thumb.get("url") if isinstance(thumb, dict) else str(thumb)
        if thumbnail:
            thumbnail = thumbnail.split("?")[0]

        channel = data.get("channel") if isinstance(data.get("channel"), dict) else {}
        url = data.get("link") or data.get("webpage_url") or fallback_url or f"{self.base}{track_id}"
        if isinstance(url, str) and "&list=" in url:
            url = url.split("&list=", 1)[0]

        duration = data.get("duration")
        duration_sec = data.get("duration_sec")
        if duration_sec is None:
            raw = data.get("duration_seconds") or data.get("duration")
            duration_sec = raw if isinstance(raw, int) else (time_to_seconds(duration) if duration else 0)
        if not duration:
            duration = self.format_duration(duration_sec or 0)

        view_count = data.get("viewCount")
        if isinstance(view_count, dict):
            view_count = view_count.get("short")

        return Track(
            id=str(track_id),
            album=data.get("album"),
            channel_name=channel.get("name")
            or data.get("channel_name")
            or data.get("uploader")
            or data.get("artist"),
            duration=duration or "00:00",
            duration_sec=int(duration_sec or 0),
            message_id=m_id,
            title=self.trim_title(data.get("title")) or "Unknown Title",
            thumbnail=thumbnail,
            url=url,
            view_count=view_count or data.get("view_count"),
            video=video,
            stream_mode=mode,
        )

    async def search(self, query: str, m_id: int, video: bool = False, mode: str = "balanced") -> Track | None:
        query = (query or "").strip()
        if not query:
            return None

        resolved_id = self.extract_video_id(query)
        if resolved_id:
            info = await self._info(self.base + resolved_id)
            if info:
                return self._build_track(data=info, m_id=m_id, video=video, mode=mode)

        key = (" ".join(query.casefold().split()), video, mode)
        return await self._search_cache.memoize(
            key,
            lambda: self._search_first(query, m_id, video, mode),
            copy=lambda track: replace(track, message_id=m_id),
        )

    async def _search_first(self, query: str, m_id: int, video: bool, mode: str) -> Track | None:
        results = await self._search_raw(query, 1)
        if not results:
            return None
        return self._build_track(data=results[0], m_id=m_id, video=video, mode=mode)

    async def search_multi(
        self, query: str, limit: int = 15, video: bool = False, mode: str = "balanced"
    ) -> list[Track]:
        query = " ".join((query or "").casefold().split())
        if not query:
            return []
        key = (query, video, mode, max(1, limit))
        return await self._multi_cache.memoize(
            key,
            lambda: self._search_many(query, limit, video, mode),
            copy=lambda tracks: [replace(track) for track in tracks],
        )

    async def _search_many(self, query: str, limit: int, video: bool, mode: str) -> list[Track]:
        results = await self._search_raw(query, limit)
        tracks: list[Track] = []
        for item in results:
            track = self._build_track(data=item, video=video, mode=mode)
            if track:
                tracks.append(track)
        return tracks

    async def advanced_search(
        self, query: str, limit: int = 5, video: bool = False, mode: str = "balanced"
    ) -> list[Track]:
        candidates = await self.search_multi(query, limit=max(limit * 3, 10), video=video, mode=mode)
        if not candidates:
            return []

        cleaned = self._clean_query(query)
        artist_hint, title_hint = self._split_title_artist(cleaned)
        scored: list[tuple[int, Track]] = []
        seen: set[str] = set()

        for index, track in enumerate(candidates):
            if not track or not track.id or track.id in seen:
                continue
            seen.add(track.id)
            score = 0
            if title_hint and self._text_matches(track.title, title_hint):
                score += 8
            elif cleaned and self._text_matches(track.title, cleaned):
                score += 5
            artist = self._primary_artist(track)
            if artist_hint and artist and self._text_matches(artist, artist_hint):
                score += 7
            if track.duration_sec > 0:
                score += 2
            if track.duration_sec > 900:
                score -= 2
            scored.append((score - index, track))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [track for _, track in scored[:limit]]

    async def search_best(
        self,
        query: str,
        m_id: int,
        *,
        video: bool = False,
        mode: str = "balanced",
        title_hint: str | None = None,
        artist_hint: str | None = None,
        album_hint: str | None = None,
        limit: int = 5,
    ) -> Track | None:
        resolved_id = self.extract_video_id(query)
        if resolved_id:
            info = await self._info(self.base + resolved_id)
            if info:
                return self._build_track(data=info, m_id=m_id, video=video, mode=mode)

        results = await self._search_raw(query, limit)
        best_item, best_score = None, -1
        for item in results:
            score = self._score_candidate(
                item, title_hint=title_hint, artist_hint=artist_hint, album_hint=album_hint
            )
            if score > best_score:
                best_item, best_score = item, score
        if best_item:
            return self._build_track(data=best_item, m_id=m_id, video=video, mode=mode)
        return None

    async def _info(self, url: str) -> dict | None:
        return await self._info_cache.memoize(url, lambda: self.downloader.extract_info(url))

    async def _flat(self, url: str) -> dict | None:
        return await self._flat_cache.memoize(
            url, lambda: self.downloader.extract_info(url, flat=True)
        )

    async def details(
        self, query: Track | dict | str, is_url: bool = True
    ) -> tuple[str, str, int, str]:
        if isinstance(query, Track):
            return query.title, query.duration, query.duration_sec, query.id

        data = query if isinstance(query, dict) else await self._info(
            query if is_url else f"https://www.youtube.com/results?search_query={query}"
        )
        entries = (data or {}).get("entries") or []
        if isinstance(data, dict) and entries:
            data = next((entry for entry in entries if entry), {})

        if isinstance(data, dict) and data.get("id"):
            track = self._build_track(data=data, fallback_url=data.get("webpage_url"))
            if track:
                return track.title, track.duration, track.duration_sec, track.id

        found = await self.search(str(query), 0)
        if not found:
            raise ValueError("Unable to fetch track details.")
        return found.title, found.duration, found.duration_sec, found.id

    async def track(self, query: str, video: bool = False) -> tuple[TrackDetails, str]:
        resolved = (
            await self.resolve_music_url(query, 0, video=video)
            if self.is_music_url(query) and not self.valid(query)
            else await self.search(query, 0, video=video)
        )
        if not resolved:
            raise ValueError(f"No matching track was found for {query!r}.")
        return {
            "title": resolved.title or "Unknown Title",
            "link": resolved.url,
            "vidid": resolved.id,
            "duration_min": resolved.duration or "00:00",
            "duration_sec": resolved.duration_sec,
        }, resolved.id

    async def slider(self, query: str, index: int = 0) -> tuple[str, str, str]:
        results = await self.search_multi(query, limit=10)
        if not results:
            raise ValueError("No search results were found.")
        track = results[index % len(results)]
        return track.title, track.duration, track.id

    async def resolve_music_url(
        self, url: str, m_id: int, video: bool = False, mode: str = "balanced"
    ) -> Track | None:
        host = (urlparse(url).hostname or "").lower()

        if host == "open.spotify.com" or host.endswith(".spotify.com"):
            title, artist, album = await self._spotify_metadata(url)
            parts = [part.strip() for part in (artist, title, album) if part and part.strip()]
            if parts:
                return await self.search(" - ".join(dict.fromkeys(parts)), m_id, video=video, mode=mode)
            return None

        info = await self._info(url)
        if not info:
            return None
        title = info.get("track") or info.get("title") or ""
        artist = info.get("artist") or info.get("uploader") or info.get("channel") or ""
        album = info.get("album") or ""
        if isinstance(artist, dict):
            artist = artist.get("name") or ""
        parts = [part.strip() for part in (artist, title, album) if part and part.strip()]
        if not parts:
            return None
        return await self.search(" - ".join(dict.fromkeys(parts)), m_id, video=video, mode=mode)

    async def _spotify_metadata(self, url: str) -> tuple[str, str, str]:
        try:
            session = await self._client()
            async with session.get(
                "https://open.spotify.com/oembed", params={"url": url}, timeout=8
            ) as response:
                if response.status != 200:
                    return "", "", ""
                payload = await response.json()
        except (TimeoutError, aiohttp.ClientError, ValueError):
            LOGGER.debug("Spotify metadata lookup failed for %s", url)
            return "", "", ""
        title = (payload.get("title") or "").strip()
        if not title:
            return "", "", ""
        song, sep, artist = title.partition(" - ")
        return (song.strip(), artist.strip(), "") if sep else (title, "", "")

    async def playlist(
        self, url: str, limit: int = PLAYLIST_FETCH_LIMIT, user=None, video: bool = False, mode: str = "balanced"
    ) -> list[Track]:
        limit = max(1, min(int(limit or PLAYLIST_FETCH_LIMIT), 100))
        tracks: list[Track] = []

        if YtPlaylist is not None:
            try:
                playlist = await YtPlaylist.get(url)
                videos = (playlist or {}).get("videos") or []
                for entry in videos[:limit]:
                    track = self._build_track(data=entry, video=video, mode=mode)
                    if track:
                        track.user = user
                        tracks.append(track)
            except Exception as exc:
                LOGGER.debug("py_yt playlist lookup failed for %s: %s", url, exc)

        if tracks:
            return tracks

        info = await self._flat(url)
        for entry in ((info or {}).get("entries") or [])[:limit]:
            if not isinstance(entry, dict):
                continue
            track = self._build_track(
                data=entry, video=video, mode=mode, fallback_url=entry.get("url")
            )
            if track:
                track.user = user
                tracks.append(track)
        return tracks

    async def related_tracks(
        self, track: Track | None, limit: int = 4, mode: str = "balanced", refresh_token: int = 0
    ) -> list[Track]:
        if not track:
            return []

        queries = self._recommendation_queries(track)
        if not queries:
            return []

        suggestions: dict[str, Track] = {}
        seen = {getattr(track, "id", None)}
        search_limit = max(limit * 3, 10)

        pages = await asyncio.gather(
            *(self._search_raw(query, search_limit) for query in queries),
            return_exceptions=True,
        )
        for page in pages:
            if not isinstance(page, list):
                continue
            for item in page:
                built = self._build_track(
                    data=item, video=getattr(track, "video", False), mode=mode
                )
                if built and built.id not in seen:
                    seen.add(built.id)
                    suggestions[built.id] = built

        if len(suggestions) < limit:
            for built in await self._mix_candidates(track, mode=mode):
                if built.id not in seen:
                    seen.add(built.id)
                    suggestions[built.id] = built

        items = [item for item in suggestions.values() if not self._is_same_track(track, item)]
        random.Random(f"{getattr(track, 'id', 'mix')}:{refresh_token}").shuffle(items)
        items.sort(key=lambda item: self._related_score(track, item), reverse=True)
        return items[:limit]

    async def _mix_candidates(self, track: Track, *, mode: str = "balanced") -> list[Track]:
        track_id = self.extract_video_id(getattr(track, "id", None) or getattr(track, "url", None))
        if not track_id:
            return []
        info = await self._flat(f"{self.base}{track_id}&list=RD{track_id}")
        found = []
        for item in (info or {}).get("entries") or []:
            if isinstance(item, dict):
                built = self._build_track(
                    data=item,
                    video=getattr(track, "video", False),
                    mode=mode,
                    fallback_url=item.get("url"),
                )
                if built:
                    found.append(built)
        return found

    async def download(
        self,
        video_id: str,
        mystic: object = None,
        video: bool = False,
        mode: str = "performance",
        videoid: bool = False,
    ) -> str | tuple[str | None, bool] | None:
        source = str(video_id or "").strip()
        if not source:
            return (None, False) if videoid else None

        resolved = self.extract_video_id(source)
        is_url = self._looks_like_url(source)
        key = resolved or self.downloader.stable_key(source)
        url = source if (resolved or is_url or self.is_stream_url(source) or self.is_music_url(source)) else self.base + key

        path = await self.downloader.download(
            url, video=video, mode=DownloadMode.parse(mode), key=key
        )
        return (path, bool(path)) if videoid else path

    async def get_audio_stream(self, video_id: str) -> dict | None:
        resolved = self.extract_video_id(video_id) or video_id
        if not resolved:
            return None
        url = video_id if self.valid(video_id) else self.base + resolved
        info = await self._info(url)
        if not info:
            return None
        _, audio_url = await self.downloader.direct_url(url, audio=True)
        if not audio_url:
            return None
        return {
            "audio_url": audio_url,
            "duration": int(info.get("duration") or 0),
            "title": self.trim_title(info.get("title"), limit=64) or "Unknown Title",
            "performer": info.get("artist") or info.get("uploader") or info.get("channel"),
        }

    async def video(self, url: str) -> tuple[int, str | None]:
        source = url if self._looks_like_url(url) else self.base + (self.extract_video_id(url) or url)
        status, direct = await self.downloader.direct_url(source, audio=False)
        return status, direct

    async def exists(self, url: str) -> bool:
        return self.valid(url) or self.is_music_url(url)

    async def url(self, message) -> str | None:
        text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
        command = getattr(message, "command", None) or []
        query = " ".join(command[1:]).strip() if len(command) > 1 else ""
        if query:
            return query

        reply = getattr(message, "reply_to_message", None)
        if reply is not None:
            reply_text = (getattr(reply, "text", None) or getattr(reply, "caption", None) or "").strip()
            if reply_text:
                return reply_text

        if text:
            parts = text.split(maxsplit=1)
            if len(parts) > 1 and parts[1].strip():
                return parts[1].strip()
        return None

    async def close(self) -> None:
        if self._http is not None and not self._http.closed:
            await self._http.close()
        self._http = None
        await self.downloader.shutdown()

    @staticmethod
    def _clean_query(value: str | None) -> str:
        if not value:
            return ""
        value = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", value)
        value = re.sub(
            r"\b(official|video|audio|lyrics|lyrical|visualizer|hd|4k|remix|version)\b",
            " ",
            value,
            flags=re.IGNORECASE,
        )
        return " ".join(value.split()).strip(" -")

    def _split_title_artist(self, title: str | None) -> tuple[str, str]:
        cleaned = self._clean_query(title)
        if not cleaned:
            return "", ""
        for separator in (" - ", " – ", " — ", ": "):
            if separator in cleaned:
                left, right = cleaned.split(separator, 1)
                artist, song = self._clean_query(left), self._clean_query(right)
                if artist and song:
                    return artist, song
        return "", cleaned

    def _artist_candidates(self, track: Track | None) -> list[str]:
        if not track or not track.channel_name:
            return []
        base = self._clean_query(track.channel_name)
        cleaned = re.sub(r"\s*-\s*topic$", "", base, flags=re.IGNORECASE).strip()
        if not cleaned:
            return []
        candidates: list[str] = []
        for value in re.split(
            r"\s*(?:,|&|/|\bx\b|\bwith\b|\bfeat\.?|\bft\.?|\bfeaturing\b)\s*",
            cleaned,
            flags=re.IGNORECASE,
        ):
            candidate = self._clean_query(value)
            if candidate and candidate not in candidates:
                candidates.append(candidate)
        if cleaned not in candidates:
            candidates.insert(0, cleaned)
        return candidates

    def _primary_artist(self, track: Track | None) -> str:
        candidates = self._artist_candidates(track)
        return candidates[0] if candidates else ""

    @staticmethod
    def _normalize_text(value: str | None) -> str:
        return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

    def _text_matches(self, left: str | None, right: str | None) -> bool:
        a = self._normalize_text(self._clean_query(left))
        b = self._normalize_text(self._clean_query(right))
        if not a or not b:
            return False
        return a == b or a in b or b in a

    def _is_same_track(self, source: Track, candidate: Track) -> bool:
        if source.id and source.id == candidate.id:
            return True
        if self._text_matches(source.title, candidate.title):
            source_artist, candidate_artist = self._primary_artist(source), self._primary_artist(candidate)
            if not source_artist or not candidate_artist:
                return True
            return self._text_matches(source_artist, candidate_artist)
        return False

    def _related_score(self, source: Track, candidate: Track) -> int:
        score = 0
        source_artist, candidate_artist = self._primary_artist(source), self._primary_artist(candidate)
        if source_artist and candidate_artist and self._text_matches(source_artist, candidate_artist):
            score += 8
        if (
            source.album
            and candidate.album
            and self._text_matches(source.album, candidate.album)
        ):
            score += 3
        if self._text_matches(source.title, candidate.title):
            score -= 10
        elif any(token in (candidate.title or "").lower() for token in ("mix", "playlist", "live", "hour", "loop")):
            score -= 2
        return score

    def _score_candidate(
        self,
        item: dict,
        *,
        title_hint: str | None = None,
        artist_hint: str | None = None,
        album_hint: str | None = None,
    ) -> int:
        title = self._clean_query(item.get("title"))
        channel = self._clean_query((item.get("channel") or {}).get("name"))
        score = 0
        if title_hint and self._text_matches(title, title_hint):
            score += 8
        if artist_hint and (
            self._text_matches(channel, artist_hint) or self._text_matches(title, artist_hint)
        ):
            score += 10
        if album_hint and self._text_matches(title, album_hint):
            score += 4
        if item.get("duration") and item.get("duration") != "0:00":
            score += 1
        return score

    def _recommendation_queries(self, track: Track) -> list[str]:
        raw_title = self._clean_query(track.title)
        title_artist, song_title = self._split_title_artist(raw_title)
        title = song_title or raw_title
        channel = self._clean_query(track.channel_name)
        artist = self._primary_artist(track) or title_artist
        album = self._clean_query(track.album)
        queries: list[str] = []
        for value in (
            " - ".join(part for part in (artist, title) if part),
            " - ".join(part for part in (title, channel) if part),
            f"{artist} {album}".strip() if artist and album else "",
            title,
            f"{channel} {title}".strip() if channel else "",
            f"{artist} songs".strip() if artist else "",
        ):
            if value and value not in queries:
                queries.append(value)
        return queries

YouTubeAPI = YouTube
