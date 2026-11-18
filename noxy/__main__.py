from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import signal
import sys
import time

from pyrogram import idle

from noxy import config
from noxy.core.call import noxy
from noxy.core.i18n import get_text
from noxy.database import drain_background_tasks
from noxy.database.mongo import ensure_indexes, ping_database
from noxy.modules import ALL_MODULES
from noxy.services.cookies import cookies

_started_at = time.perf_counter()
LOGGER = logging.getLogger("noximusic")


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    for noisy in ("pyrogram", "pytgcalls", "ntgcalls", "py_yt", "aiohttp", "pymongo"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def load_modules() -> int:
    loaded = 0
    failures: list[str] = []

    for module in ALL_MODULES:
        try:
            loaded_module = importlib.import_module(f"noxy.modules{module}")
            starter = getattr(loaded_module, "start_background_tasks", None)
            if callable(starter):
                result = starter()
                if inspect.isawaitable(result):
                    await result
        except Exception:
            failures.append(module)
            LOGGER.exception("Failed to load or initialize module %s", module)
            continue
        loaded += 1

    LOGGER.info("Loaded %d/%d command modules.", loaded, len(ALL_MODULES))
    if failures:
        failed = ", ".join(failures)
        raise RuntimeError(f"Failed to load required command modules: {failed}")
    return loaded


async def _announce(client, key: str, identity: str) -> None:
    chat_id = config.LOGGER_CHAT
    if chat_id is None:
        LOGGER.debug("LOGGER_ID is not configured; skipping %s message.", key)
        return
    try:
        await client.send_message(chat_id=chat_id, text=get_text(key, identity=identity))
    except Exception:
        LOGGER.warning("Could not deliver the %s startup message.", key, exc_info=True)


async def main() -> None:
    configure_logging()
    started: list[str] = []

    try:
        db_ready, _ = await asyncio.gather(
            ping_database(),
            cookies.initialize(),
            return_exceptions=False,
        )
        if not db_ready:
            raise RuntimeError("MongoDB is unreachable. Check MONGO_URI and network access.")
        LOGGER.info("MongoDB connected.")
        await ensure_indexes()

        from noxy import app, userbot

        started.append("bot")
        await app.start()

        started.append("userbot")
        await userbot.start()

        await _announce(app, "startup.bot_started", f"@{app.username}" if app.username else app.mention)
        for _slot, client in userbot.started:
            await _announce(
                client,
                "startup.assistant_started",
                f"@{client.username}" if client.username else client.mention,
            )

        started.append("calls")
        await noxy.start()

        await load_modules()
        await noxy.decorators()

        LOGGER.info(
            "NoxiMusic is ready in %.2fs — %d assistant(s) online.",
            time.perf_counter() - _started_at,
            len(userbot.started),
        )
        await idle()
    except asyncio.CancelledError:
        LOGGER.info("Shutdown requested.")
    except Exception:
        LOGGER.exception("Fatal startup or runtime error.")
        raise
    finally:
        LOGGER.info("Shutting down NoxiMusic…")
        await _shutdown(started)


async def _shutdown(started: list[str]) -> None:
    from noxy import app, downloader, userbot

    if "calls" in started:
        await _safe(noxy.stop, "voice-call clients")
    if "userbot" in started:
        await _safe(userbot.stop, "assistant clients")
    if "bot" in started:
        await _safe(app.stop, "bot client")

    await _safe(drain_background_tasks, "database writes")
    await _safe(downloader.shutdown, "download worker pool")

    from noxy.database.mongo import close_database

    await _safe(close_database, "database client")
    LOGGER.info("Shutdown complete.")


async def _safe(func, label: str) -> None:
    try:
        result = func()
        if inspect.isawaitable(result):
            await result
    except Exception:
        LOGGER.exception("Failed to stop %s cleanly.", label)


def run() -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    main_task: asyncio.Task | None = None

    async def _runner() -> None:
        nonlocal main_task
        main_task = asyncio.current_task()
        await main()

    def _request_stop(*_args) -> None:
        if main_task and not main_task.done():
            main_task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _request_stop)
        except (NotImplementedError, RuntimeError):
            signal.signal(sig, lambda *_: _request_stop())

    try:
        loop.run_until_complete(_runner())
    except KeyboardInterrupt:
        LOGGER.info("Interrupted.")
    finally:
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

if __name__ == "__main__":
    run()
