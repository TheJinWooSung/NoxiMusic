from __future__ import annotations

import asyncio
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import aiohttp
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

DEFAULT_THUMB_URL = "https://i.ibb.co/7x18pjVW/tmpgpsp2f4s.jpg"
DEFAULT_THUMB = os.getenv("DEFAULT_THUMB", DEFAULT_THUMB_URL).strip() or DEFAULT_THUMB_URL

LOGGER = logging.getLogger(__name__)
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
VIDEO_ID_SEARCH = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])")
WIDTH, HEIGHT = 1280, 720
DESIGN_VERSION = "v3"
FONT_PATHS = (
    Path(__file__).with_name("font.ttf"),
    Path(__file__).with_name("font2.ttf"),
)
_LOCKS: dict[str, asyncio.Lock] = {}


def _video_id(value: str | None) -> str | None:
    if not value:
        return None
    value = str(value).strip()
    if VIDEO_ID.fullmatch(value):
        return value
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if host.endswith("youtu.be"):
        candidate = parsed.path.strip("/").split("/", 1)[0]
        return candidate if VIDEO_ID.fullmatch(candidate) else None
    if host.endswith("youtube.com"):
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
        if not candidate:
            parts = parsed.path.strip("/").split("/")
            candidate = parts[1] if len(parts) > 1 and parts[0] in {"shorts", "embed", "live"} else ""
        return candidate if VIDEO_ID.fullmatch(candidate) else None
    match = VIDEO_ID_SEARCH.search(value)
    return match.group(1) if match else None


@lru_cache(maxsize=8)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(str(path), size)
        except OSError:
            LOGGER.warning("Could not load bundled thumbnail font: %s", path)
    return ImageFont.load_default()


def _safe_text(value: str) -> str:
    return value.encode("ascii", "replace").decode("ascii")


def _draw_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, font, **kwargs) -> None:
    try:
        draw.text(xy, value, font=font, **kwargs)
    except (UnicodeEncodeError, OSError):
        draw.text(xy, _safe_text(value), font=font, **kwargs)


def _text_width(draw: ImageDraw.ImageDraw, value: str, font) -> int:
    try:
        return draw.textbbox((0, 0), value, font=font)[2]
    except (UnicodeEncodeError, OSError):
        return draw.textbbox((0, 0), _safe_text(value), font=font)[2]


def _fit_title(draw: ImageDraw.ImageDraw, value: str, font, width: int) -> str:
    title = " ".join(str(value or "Now Playing").split())
    while title and _text_width(draw, title, font) > width:
        title = title[:-2].rstrip() + "…"
    return title or "Now Playing"


def _render(
    source: Path | None,
    output: Path,
    title: str,
    duration: str,
    username: str,
) -> str:
    if source and source.is_file():
        with Image.open(source) as image:
            artwork = ImageOps.fit(
                image.convert("RGB"), (472, 472), method=Image.Resampling.LANCZOS
            )
    else:
        artwork = Image.new("RGB", (472, 472), (25, 36, 55))

    backdrop = artwork.resize((96, 96), Image.Resampling.BILINEAR)
    backdrop = backdrop.filter(ImageFilter.GaussianBlur(28)).resize(
        (WIDTH, HEIGHT), Image.Resampling.BILINEAR
    )
    canvas = ImageEnhance.Brightness(backdrop).enhance(0.20).convert("RGBA")
    shade = Image.new("RGBA", (WIDTH, HEIGHT), (5, 10, 22, 170))
    canvas.alpha_composite(shade)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (54, 48, 1226, 672),
        radius=42,
        fill=(10, 17, 32, 238),
        outline=(91, 111, 139, 105),
        width=2,
    )
    draw.rounded_rectangle((94, 88, 590, 584), radius=34, fill=(24, 34, 53, 255))

    shadow = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        (14, 14, 498, 498), radius=30, fill=(0, 0, 0, 120)
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(shadow, (91, 91))

    mask = Image.new("L", artwork.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 471, 471), radius=28, fill=255)
    canvas.paste(artwork, (106, 106), mask)

    accent = "#65E5D5"
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((642, 116, 836, 160), radius=22, fill=(31, 67, 72, 255))
    draw.ellipse((660, 132, 672, 144), fill=accent)
    _draw_text(draw, (686, 125), "NOW PLAYING", _font(18), fill=accent)

    _draw_text(draw, (642, 202), "NOXIMUSIC", _font(21), fill="#A9B8CA")
    title_font = _font(52)
    title_text = _fit_title(draw, title, title_font, 520)
    _draw_text(draw, (638, 258), title_text, title_font, fill="#FFFFFF")

    artist = f"REQUESTED BY  @{username or 'NOXIMUSIC'}"
    _draw_text(draw, (642, 344), artist, _font(17), fill="#AAB8C9")

    draw.rounded_rectangle((642, 414, 1144, 416), radius=1, fill=(72, 91, 112, 190))
    bars = (16, 28, 21, 38, 25, 48, 31, 18, 40, 26, 51, 32, 20, 43, 29, 17, 36, 24, 46, 30, 19, 39)
    for index, height in enumerate(bars):
        x = 646 + index * 21
        draw.rounded_rectangle(
            (x, 482 - height // 2, x + 8, 482 + height // 2),
            radius=4,
            fill=accent if index < 7 else (96, 122, 143, 230),
        )

    draw.rounded_rectangle((642, 548, 1144, 555), radius=4, fill=(67, 82, 101, 255))
    draw.rounded_rectangle((642, 548, 735, 555), radius=4, fill=accent)
    _draw_text(draw, (642, 574), "00:00", _font(17), fill="#D5DFEA")
    _draw_text(draw, (1082, 574), duration or "LIVE", _font(17), fill="#D5DFEA")

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(
        output, format="JPEG", quality=90, optimize=False, progressive=False
    )
    return str(output)


async def _download_image(
    session: aiohttp.ClientSession, url: str, target: Path
) -> bool:
    try:
        async with session.get(url) as response:
            if response.status != 200:
                return False
            data = await response.read()
        target.write_bytes(data)
        with Image.open(target) as image:
            image.verify()
        return True
    except (aiohttp.ClientError, TimeoutError, OSError, ValueError):
        target.unlink(missing_ok=True)
        return False


def _valid_image(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        return True
    except (OSError, ValueError):
        return False


async def get_thumb(
    videoid: str,
    title: str = "Now Playing",
    duration: str = "00:00",
    username: str = "",
) -> str:
    video_id = _video_id(videoid)
    cache_key = video_id or re.sub(r"[^A-Za-z0-9_-]", "_", str(title))[:48] or "default"
    cache_path = CACHE_DIR / f"{cache_key}_player_{DESIGN_VERSION}.jpg"
    if _valid_image(cache_path):
        return str(cache_path)

    lock = _LOCKS.setdefault(cache_key, asyncio.Lock())
    async with lock:
        if _valid_image(cache_path):
            return str(cache_path)

        source_path = CACHE_DIR / f"{cache_key}_source.jpg"
        downloaded = False
        if video_id:
            timeout = aiohttp.ClientTimeout(total=3.5, connect=2)
            try:
                async with aiohttp.ClientSession(
                    timeout=timeout,
                    connector=aiohttp.TCPConnector(limit=4, ttl_dns_cache=300),
                ) as session:
                    downloaded = await _download_image(
                        session,
                        f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
                        source_path,
                    )
            except (aiohttp.ClientError, TimeoutError, OSError):
                LOGGER.debug("Thumbnail artwork fetch failed for %s", video_id)

        try:
            result = await asyncio.to_thread(
                _render,
                source_path if downloaded else None,
                cache_path,
                title,
                duration,
                username,
            )
            if _valid_image(cache_path):
                return result
            raise OSError("Generated thumbnail failed image validation")
        except Exception:
            LOGGER.exception("Thumbnail generation failed for video %s", videoid or "<missing-id>")
            return DEFAULT_THUMB
        finally:
            source_path.unlink(missing_ok=True)


__all__ = ["get_thumb"]
