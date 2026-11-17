from __future__ import annotations

import logging
from typing import Final

from pymongo import AsyncMongoClient
from pymongo.asynchronous.collection import AsyncCollection
from pymongo.errors import PyMongoError

from noxy.config import MONGO_URI

LOGGER = logging.getLogger(__name__)

DATABASE_NAME: Final[str] = "noximusic"

client: Final[AsyncMongoClient] = AsyncMongoClient(
    MONGO_URI,
    connect=False,
    retryWrites=True,
    appname="NoxiMusic",
)
database = client[DATABASE_NAME]

_COLLECTIONS: Final[dict[str, AsyncCollection]] = {}


def get_collection(name: str) -> AsyncCollection:
    collection = _COLLECTIONS.get(name)
    if collection is None:
        collection = database[name]
        _COLLECTIONS[name] = collection
    return collection


authdb = get_collection("adminauth")
autoenddb = get_collection("autoend")
assdb = get_collection("assistants")
chatsdb = get_collection("chats")
playmodedb = get_collection("playmode")
playtypedb = get_collection("playtypedb")
skipdb = get_collection("skipmode")
autoplaydb = get_collection("autoplay")
usersdb = get_collection("tgusersdb")
languagesdb = get_collection("languages")


async def ping_database() -> bool:
    try:
        await client.admin.command("ping")
    except PyMongoError:
        LOGGER.exception("MongoDB ping failed.")
        return False
    return True


async def close_database() -> None:
    await client.close()


async def ensure_indexes() -> None:
    plans = (
        (authdb, "chat_id"),
        (autoenddb, "chat_id"),
        (assdb, "chat_id"),
        (chatsdb, "chat_id"),
        (playmodedb, "chat_id"),
        (playtypedb, "chat_id"),
        (autoplaydb, "chat_id"),
        (languagesdb, "user_id"),
        (usersdb, "user_id"),
    )
    for collection, field in plans:
        try:
            await collection.create_index(field, unique=True, name=f"{field}_unique")
        except PyMongoError:
            LOGGER.warning("Could not ensure index on %s.%s", collection.name, field)
