from __future__ import annotations

from urllib.parse import urlparse

from noxy.services.youtube import YouTube


class ProviderAPI:
    domains: tuple[str, ...] = ()

    def __init__(self, engine: YouTube | None = None, domains: tuple[str, ...] = ()) -> None:
        self.engine = engine or YouTube()
        if domains:
            self.domains = tuple(domains)

    async def valid(self, link: str) -> bool:
        host = (urlparse(link).hostname or "").lower()
        return bool(host) and any(
            host == domain or host.endswith("." + domain) for domain in self.domains
        )

    async def track(self, url: str, playid=None):
        return await self.engine.track(url)

    async def playlist(self, url: str, playid=None):
        info = await self.engine._flat(url)
        entries = (info or {}).get("entries") or []
        titles = []
        for item in entries[:100]:
            if isinstance(item, dict):
                title = (item.get("title") or "").strip()
                if title:
                    titles.append(title)
        return titles, (info or {}).get("id") or url

    async def album(self, url: str):
        return await self.playlist(url)

    async def artist(self, url: str):
        return await self.playlist(url)

    async def download(self, url: str):
        info = await self.engine._info(url)
        if not info:
            raise ValueError("Unable to resolve this media URL.")
        filepath = await self.engine.download(url)
        if not filepath:
            raise ValueError("Media download failed.")
        duration = int(info.get("duration") or 0)
        return {
            "title": info.get("title") or "Unknown Title",
            "duration_sec": duration,
            "duration_min": self.engine.format_duration(duration),
            "uploader": info.get("uploader") or info.get("channel") or "",
            "filepath": filepath,
        }, filepath


class AppleAPI(ProviderAPI):
    domains = ("music.apple.com", "geo.music.apple.com")


class RessoAPI(ProviderAPI):
    domains = ("resso.com",)


class SoundAPI(ProviderAPI):
    domains = ("soundcloud.com", "on.soundcloud.com")


class SpotifyAPI(ProviderAPI):
    domains = ("spotify.com", "open.spotify.com")
