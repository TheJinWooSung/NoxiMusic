<p align="center">
  <img src="https://i.imgur.com/ptI1tS4.jpeg" alt="NoxiMusic banner" width="100%" />
</p>

<h1 align="center">NoxiMusic</h1>

<p align="center">
  <strong>Telegram group voice-chat music bot</strong>
</p>

<p align="center">
  Kurigram · PyTgCalls · NTgCalls · yt-dlp · MongoDB
</p>

<p align="center">
  <a href="https://github.com/TheJinWooSung/NoxiMusic">Repository</a> ·
  <a href="https://github.com/TheJinWooSung/NoxiMusic/issues">Issues</a> ·
  <a href="https://github.com/TheJinWooSung/NoxiMusic/stargazers">Stars</a>
</p>

## Overview

NoxiMusic plays music and video in Telegram group voice chats. It combines a Telegram bot with one or more assistant accounts, a persistent MongoDB-backed settings layer, and an asynchronous media pipeline.

## Features

- Audio and video playback in group voice chats
- YouTube search, direct links, playlists, live streams and mixes
- Spotify, Apple Music, SoundCloud, Resso and Telegram media support
- Queue management, force play, loop, autoplay, seek and playback speed
- Multiple assistant sessions
- Per-chat playback settings and saved playlists
- Multilingual command interface
- Docker support and graceful shutdown

## Requirements

- Python 3.11 or newer
- Telegram API credentials
- A Telegram bot token
- At least one assistant session string
- MongoDB Atlas or a self-hosted MongoDB server
- FFmpeg and ffprobe when running outside the included Docker image
- Deno recommended for supported yt-dlp formats
- aria2 optional for external downloads

## Quick start

Clone the repository and create your environment file:

```bash
git clone https://github.com/TheJinWooSung/NoxiMusic.git
cd NoxiMusic
cp .env.example .env
```

Edit `.env` and add the required credentials described below.

### Install with uv

```bash
uv sync --locked
uv run python -m noxy
```

### Install with pip

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m noxy
```

On Windows, activate the virtual environment with `.venv\\Scripts\\activate`.

## Configuration

The example file lists only essential credentials. Optional tuning variables are read by the modules that use them and are documented below.

| Variable | Required | Description |
| --- | --- | --- |
| `API_ID` | Yes | Telegram API ID from [my.telegram.org](https://my.telegram.org) |
| `API_HASH` | Yes | Telegram API hash from [my.telegram.org](https://my.telegram.org) |
| `BOT_TOKEN` | Yes | Bot token from [@BotFather](https://t.me/BotFather) |
| `MONGO_URI` | Yes | MongoDB connection URI |
| `STRING1` | Yes | Session string for the primary voice-chat assistant |
| `STRING2`–`STRING5` | No | Additional assistant session strings |
| `OWNER_ID` | No | Numeric Telegram user ID for owner-only commands |
| `LOGGER_ID` | No | Chat or channel ID for startup and error logs |
| `COOKIES_URL` | No | HTTPS URL of a raw Netscape-format cookie file |

### Getting the credentials

1. Open [my.telegram.org](https://my.telegram.org), sign in with your Telegram account, open **API development tools**, and copy the API ID and API hash.
2. Open [@BotFather](https://t.me/BotFather), create a bot with `/newbot`, and copy its token.
3. Create a MongoDB deployment, create a database user, allow your host to connect, and copy the application connection URI. Keep the URI private.
4. Generate a Kurigram/Pyrogram session string using a Telegram account you control. Use a separate account for the assistant and keep the session string secret.
5. Add the values to `.env`. Never commit `.env`, bot tokens, MongoDB credentials or session strings.

The database name is selected internally by the application. Set only `MONGO_URI`; a separate database-name variable is not needed.

### Optional cookies

If a source requires authenticated YouTube access, set `COOKIES_URL` to a private HTTPS URL that serves the raw Netscape cookie file. Keep the file private and use a direct raw-file URL rather than an HTML preview page.

## Docker

The repository includes a Dockerfile and Compose configuration:

```bash
docker compose up -d --build
docker compose logs -f
```

Set the same environment variables in your hosting provider when deploying from the Dockerfile. Do not upload your local `.env` file to a public repository.

## Commands

| Command | Description |
| --- | --- |
| `/start` | Open the bot start panel |
| `/help` | Browse command help |
| `/play` | Play audio from a search or supported URL |
| `/vplay` | Play video in the voice chat |
| `/playforce`, `/vplayforce` | Replace the current stream |
| `/pause`, `/resume` | Pause or resume playback |
| `/skip`, `/next` | Skip tracks |
| `/queue` | View queued tracks |
| `/seek`, `/seekback` | Change the playback position |
| `/speed` | Change playback speed |
| `/loop` | Configure track looping |
| `/autoplay` | Configure related-track autoplay |
| `/settings` | Change group playback settings |
| `/stop`, `/end` | Stop playback and clear the queue |
| `/ping` | Check bot and system response |
| `/admincache` | Refresh the group administrator cache |\n| `/stats` | View bot statistics |\n| `/broadcast` | Send an owner announcement |

Some commands are restricted to group administrators, authorized users or the bot owner.

## Runtime tuning

Optional performance values are read by the module that owns them:

| Variable | Module | Default |
| --- | --- | --- |
| `DOWNLOAD_MODE` | `noxy/services/downloader.py` | `balanced` |
| `YTDLP_CHUNK_SIZE` | `noxy/services/downloader.py` | `10M` |
| `ARIA2C_ENABLED` | `noxy/services/downloader.py` | `false` |
| `ARIA2C_CONNECTIONS` | `noxy/services/downloader.py` | `16` |
| `TG_AUDIO_FILESIZE_LIMIT` | `noxy/services/downloader.py` | `100 MiB` |
| `TG_VIDEO_FILESIZE_LIMIT` | `noxy/services/downloader.py` | `4 GiB` |
| `AUTO_LEAVING_ASSISTANT` | `noxy/core/settings.py` | `false` |
| `PREFETCH_ENABLED` | `noxy/core/settings.py` | `true` |
| `PREFETCH_COUNT` | `noxy/core/settings.py` | `1` |
| `HTTP_TIMEOUT` | `noxy/services/youtube.py` | `10` seconds |
| `DEFAULT_THUMB` | `noxy/helpers/thumbnail.py` | Built-in thumbnail |

Shared queue and playback limits are defined in `noxy/core/limits.py`.

## Development

```bash
uv sync --locked --extra dev
uv run ruff check noxy tests
uv run pytest -q
```

## Troubleshooting

- **MongoDB connection fails:** verify `MONGO_URI`, database-user credentials and network access rules.
- **Bot does not start:** verify `API_ID`, `API_HASH` and `BOT_TOKEN`.
- **Assistant cannot join:** check that the session is valid and the account can join the group's voice chat.
- **No assistant session configured:** add at least `STRING1`.
- **FFmpeg is missing:** install FFmpeg and ensure both `ffmpeg` and `ffprobe` are available on `PATH`.
- **Authenticated YouTube media fails:** check that `COOKIES_URL` serves a valid raw Netscape cookie file.

## License

NoxiMusic is distributed under the MIT License. See [LICENSE](LICENSE).
