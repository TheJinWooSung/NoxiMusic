from __future__ import annotations

import asyncio
import logging

from pyrogram import Client

from noxy.config import API_HASH, API_ID, SESSION_STRINGS

LOGGER = logging.getLogger(__name__)

assistants: dict[int, Client] = {}
assistant_ids: dict[int, int] = {}
assistantids: list[int] = []


class AssistantManager:
    def __init__(self) -> None:
        self._clients: list[tuple[int, str, Client]] = []
        for slot, session in SESSION_STRINGS:
            if not session or not session.strip():
                continue
            client = Client(
                name=f"NoxiMusic{slot}",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session.strip(),
                in_memory=True,
                sleep_threshold=0,
                max_concurrent_transmissions=8,
            )
            self._clients.append((slot, session.strip(), client))

        self._started: list[tuple[int, Client]] = []
        self.id = 0
        self.name = ""
        self.username = ""
        self.mention = ""

    @property
    def clients(self) -> tuple[tuple[str, int, Client], ...]:
        return tuple(
            (session, slot, client)
            for slot, session, client in self._clients
        )

    def __getattr__(self, item: str):
        names = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
        slot = names.get(item)
        if slot is not None:
            for configured_slot, _session, client in self._clients:
                if configured_slot == slot:
                    return client
        raise AttributeError(item)

    @property
    def started(self) -> list[tuple[int, Client]]:
        return list(self._started)

    async def start(self) -> None:
        if not self._clients:
            raise RuntimeError(
                "No assistant session is configured. Set at least one STRING1-STRING5 value."
            )

        LOGGER.info("Starting %d assistant client(s)…", len(self._clients))

        async def _start_one(slot: int, client: Client) -> tuple[int, Client]:
            await client.start()
            me = client.me
            client.id = me.id
            client.name = me.first_name
            client.username = me.username or ""
            client.mention = me.mention
            LOGGER.info(
                "Assistant %s online: %s [ID: %s]",
                slot,
                f"@{me.username}" if me.username else me.mention,
                me.id,
            )
            return slot, client

        results = await asyncio.gather(
            *(
                _start_one(slot, client)
                for slot, _session, client in self._clients
            ),
            return_exceptions=True,
        )

        failures = [result for result in results if isinstance(result, Exception)]
        for result in results:
            if isinstance(result, tuple):
                slot, client = result
                self._started.append((slot, client))
                assistants[slot] = client
                assistant_ids[slot] = client.id

        if not self._started:
            for failure in failures:
                LOGGER.error("Assistant failed to start: %s", failure)
            raise RuntimeError("No assistant client could be started.") from (
                failures[0] if failures else None
            )

        for failure in failures:
            LOGGER.warning("An assistant session failed to start: %s", failure)

        assistantids.clear()
        assistantids.extend(
            assistant_ids[slot] for slot in sorted(assistant_ids)
        )

        first_slot = min(assistants)
        primary = assistants[first_slot]
        self.id = assistant_ids[first_slot]
        self.name = primary.mention
        self.username = primary.username or ""
        self.mention = primary.mention

        LOGGER.info(
            "Assistant clients ready: %d/%d",
            len(self._started),
            len(self._clients),
        )

    async def stop(self) -> None:
        LOGGER.info("Stopping assistant clients…")
        for slot, client in reversed(self._started):
            try:
                await client.stop()
            except Exception:
                LOGGER.exception("Assistant %s did not stop cleanly.", slot)

        self._started.clear()
        assistants.clear()
        assistant_ids.clear()
        assistantids.clear()
        self.id = 0
        self.name = ""
        self.username = ""
        self.mention = ""


Userbot = AssistantManager
