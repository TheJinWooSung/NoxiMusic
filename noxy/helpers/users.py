from pyrogram.enums import MessageEntityType
from pyrogram.types import Message, User

from noxy import app


async def extract_user(message: Message) -> User | None:
    reply = message.reply_to_message
    if reply and reply.from_user:
        return reply.from_user

    command = message.command or []
    if len(command) < 2:
        return None

    entities = message.entities or message.caption_entities or ()
    mention = next(
        (
            entity
            for entity in entities
            if entity.type == MessageEntityType.TEXT_MENTION and entity.user
        ),
        None,
    )
    if mention:
        return await app.get_users(mention.user.id)

    target = command[1].strip()
    if not target:
        return None

    return await app.get_users(int(target) if target.isdecimal() else target.lstrip("@"))
