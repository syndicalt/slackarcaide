"""Durable message operations and batched presentation queries."""

from __future__ import annotations

import base64
import binascii
import json
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Match, Message, Reaction
from app.realtime.publisher import publish

MAX_CHANNEL_LENGTH = 64
MAX_CONTENT = 2000
MAX_LIST_LIMIT = 100

_MENTION_RE = re.compile(
    r"@([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.I,
)


def parse_mentions(content: str) -> list[uuid.UUID]:
    seen: set[uuid.UUID] = set()
    mentions: list[uuid.UUID] = []
    for raw in _MENTION_RE.findall(content or ""):
        identifier = uuid.UUID(raw)
        if identifier not in seen:
            seen.add(identifier)
            mentions.append(identifier)
    return mentions


def normalize_message_channel(channel: str) -> str:
    value = channel.strip()
    if not value or len(value) > MAX_CHANNEL_LENGTH:
        raise ValueError("invalid_channel")
    if value == "global":
        return value
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ValueError("invalid_channel") from exc


async def validate_message_channel(session: AsyncSession, channel: str) -> str:
    value = normalize_message_channel(channel)
    if value != "global" and await session.get(Match, uuid.UUID(value)) is None:
        raise ValueError("channel_not_found")
    return value


def encode_cursor(message: Message) -> str:
    created_at = message.created_at
    if created_at.tzinfo is None:
        # SQLite drops timezone metadata. Model timestamps are UTC by policy.
        created_at = created_at.replace(tzinfo=UTC)
    payload = json.dumps([created_at.isoformat(), str(message.id)], separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(payload).decode().rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = value + "=" * (-len(value) % 4)
        raw = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(raw, list) or len(raw) != 2:
            raise ValueError
        created_at = datetime.fromisoformat(raw[0].replace("Z", "+00:00"))
        if created_at.tzinfo is None:
            raise ValueError
        identifier = uuid.UUID(raw[1])
    except (
        ValueError,
        TypeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        binascii.Error,
    ) as exc:
        raise ValueError("invalid_cursor") from exc
    return created_at, identifier


async def post_message(
    session: AsyncSession,
    *,
    channel: str,
    author_id: uuid.UUID,
    content: str,
    tick_reference: int | None = None,
    parent_id: uuid.UUID | None = None,
) -> Message:
    channel = await validate_message_channel(session, channel)
    content = content.strip()
    if not content:
        raise ValueError("message_empty")
    if len(content) > MAX_CONTENT:
        raise ValueError("message_too_long")
    if tick_reference is not None and tick_reference < 0:
        raise ValueError("invalid_tick_reference")

    if parent_id is not None:
        parent = await session.get(Message, parent_id)
        if parent is None:
            raise ValueError("parent_not_found")
        if parent.channel != channel:
            raise ValueError("parent_channel_mismatch")
        if parent.parent_id is not None:
            raise ValueError("nested_reply_not_allowed")

    message = Message(
        channel=channel,
        author_id=author_id,
        content=content,
        tick_reference=tick_reference,
        parent_id=parent_id,
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    await publish(f"messages:{channel}", message_to_dict(message))
    return message


async def list_messages(
    session: AsyncSession,
    channel: str,
    limit: int = 50,
    before: tuple[datetime, uuid.UUID] | None = None,
) -> list[Message]:
    channel = await validate_message_channel(session, channel)
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    stmt = select(Message).where(Message.channel == channel)
    if before is not None:
        created_at, identifier = before
        stmt = stmt.where(
            or_(
                Message.created_at < created_at,
                and_(Message.created_at == created_at, Message.id < identifier),
            )
        )
    stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
    return list((await session.scalars(stmt)).all())


def message_to_dict(message: Message) -> dict:
    return {
        "id": str(message.id),
        "channel": message.channel,
        "author_id": str(message.author_id),
        "content": message.content,
        "tick_reference": message.tick_reference,
        "parent_id": str(message.parent_id) if message.parent_id else None,
        "created_at": message.created_at,
    }


async def add_reaction(
    session: AsyncSession,
    message: Message,
    author_id: uuid.UUID,
    emoji: str,
) -> bool:
    emoji = emoji.strip()
    if not emoji or len(emoji) > 32:
        raise ValueError("invalid_emoji")
    session.add(Reaction(message_id=message.id, author_id=author_id, emoji=emoji))
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        return False
    await publish(
        f"messages:{message.channel}",
        {
            "type": "reaction_add",
            "message_id": str(message.id),
            "author_id": str(author_id),
            "emoji": emoji,
        },
    )
    return True


async def remove_reaction(
    session: AsyncSession,
    message: Message,
    author_id: uuid.UUID,
    emoji: str,
) -> bool:
    result = await session.execute(
        delete(Reaction).where(
            Reaction.message_id == message.id,
            Reaction.author_id == author_id,
            Reaction.emoji == emoji,
        )
    )
    await session.commit()
    removed = bool(result.rowcount)
    if removed:
        await publish(
            f"messages:{message.channel}",
            {
                "type": "reaction_remove",
                "message_id": str(message.id),
                "author_id": str(author_id),
                "emoji": emoji,
            },
        )
    return removed


async def message_details(session: AsyncSession, messages: list[Message]) -> list[dict]:
    if not messages:
        return []
    ids = [message.id for message in messages]

    reaction_rows = (
        await session.execute(
            select(Reaction.message_id, Reaction.emoji, Reaction.author_id).where(
                Reaction.message_id.in_(ids)
            )
        )
    ).all()
    reactions: dict[uuid.UUID, dict[str, dict]] = defaultdict(dict)
    for message_id, emoji, author_id in reaction_rows:
        entry = reactions[message_id].setdefault(emoji, {"count": 0, "authors": []})
        entry["count"] += 1
        entry["authors"].append(str(author_id))

    count_rows = (
        await session.execute(
            select(Message.parent_id, func.count())
            .where(Message.parent_id.in_(ids))
            .group_by(Message.parent_id)
        )
    ).all()
    reply_counts = {message_id: count for message_id, count in count_rows}

    parent_ids = {message.parent_id for message in messages if message.parent_id}
    parents = {}
    if parent_ids:
        parent_rows = (
            await session.scalars(select(Message).where(Message.id.in_(parent_ids)))
        ).all()
        parents = {parent.id: parent for parent in parent_rows}

    details: list[dict] = []
    for message in messages:
        data = message_to_dict(message)
        data["mentions"] = [str(item) for item in parse_mentions(message.content)]
        data["reactions"] = reactions.get(message.id, {})
        data["reply_count"] = reply_counts.get(message.id, 0)
        parent = parents.get(message.parent_id)
        data["quote"] = (
            {
                "id": str(parent.id),
                "author_id": str(parent.author_id),
                "content": parent.content,
            }
            if parent
            else None
        )
        details.append(data)
    return details


async def message_detail(session: AsyncSession, message: Message) -> dict:
    return (await message_details(session, [message]))[0]
