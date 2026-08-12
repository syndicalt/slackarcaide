"""Message persistence and realtime fan-out.

Messages are authoritative in Postgres/SQLite; Redis pub/sub is transport only.
post_message commits before publishing so a publish failure never leaves a
partial write.
"""
import re
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Message, Reaction
from app.realtime.publisher import publish

MAX_CONTENT = 2000
MAX_LIST_LIMIT = 100

_MENTION_RE = re.compile(r"@([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.I)


def parse_mentions(content: str) -> list[uuid.UUID]:
    """Return agent ids referenced as @<uuid> in content (order-preserving)."""
    out: list[uuid.UUID] = []
    for raw in _MENTION_RE.findall(content or ""):
        try:
            uid = uuid.UUID(raw)
        except ValueError:
            continue
        if uid not in out:
            out.append(uid)
    return out


async def post_message(
    session: AsyncSession,
    *,
    channel: str,
    author_id,
    content: str,
    tick_reference: int | None = None,
    parent_id=None,
) -> Message:
    """Persist a message, commit, then publish it to `messages:{channel}`."""
    content = content.strip()
    if not content:
        raise ValueError("message_empty")
    if len(content) > MAX_CONTENT:
        raise ValueError("message_too_long")

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

    await publish(
        f"messages:{channel}",
        await message_to_dict(message),
    )
    return message


async def list_messages(
    session: AsyncSession,
    channel: str,
    limit: int = 50,
    before=None,
) -> list[Message]:
    """Newest-first messages for a channel, capped at 100; optional created_at cursor."""
    limit = max(1, min(limit, MAX_LIST_LIMIT))
    stmt = (
        select(Message)
        .where(Message.channel == channel)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(limit)
    )
    if before is not None:
        stmt = stmt.where(Message.created_at < before)
    return list((await session.scalars(stmt)).all())


async def message_to_dict(m: Message) -> dict:
    return {
        "id": str(m.id),
        "channel": m.channel,
        "author_id": str(m.author_id),
        "content": m.content,
        "tick_reference": m.tick_reference,
        "parent_id": str(m.parent_id) if m.parent_id is not None else None,
        "created_at": m.created_at,
    }


async def add_reaction(
    session: AsyncSession,
    message: Message,
    author_id: uuid.UUID,
    emoji: str,
) -> bool:
    """Add a reaction to a message. Idempotent. Returns True if it was newly added."""
    emoji = emoji.strip()
    if not emoji or len(emoji) > 32:
        raise ValueError("invalid_emoji")
    exists = await session.scalar(
        select(Reaction).where(
            Reaction.message_id == message.id,
            Reaction.author_id == author_id,
            Reaction.emoji == emoji,
        )
    )
    if exists is not None:
        await session.commit()
        return False
    session.add(
        Reaction(message_id=message.id, author_id=author_id, emoji=emoji)
    )
    try:
        await session.commit()
    except Exception:
        await session.rollback()
        return False
    await publish(
        f"messages:{message.channel}",
        {"type": "reaction_add", "message_id": str(message.id), "emoji": emoji},
    )
    return True


async def remove_reaction(
    session: AsyncSession,
    message: Message,
    author_id: uuid.UUID,
    emoji: str,
) -> bool:
    """Remove the author's own reaction. Returns True if one was removed."""
    result = await session.execute(
        delete(Reaction).where(
            Reaction.message_id == message.id,
            Reaction.author_id == author_id,
            Reaction.emoji == emoji,
        )
    )
    await session.commit()
    removed = result.rowcount > 0
    if removed:
        await publish(
            f"messages:{message.channel}",
            {"type": "reaction_remove", "message_id": str(message.id), "emoji": emoji},
        )
    return removed


async def reaction_summary(
    session: AsyncSession, message_id: uuid.UUID
) -> dict[str, dict]:
    """Aggregate reactions: {emoji: {"count": n, "authors": [ids]}}"""
    rows = (
        await session.execute(
            select(Reaction.emoji, Reaction.author_id).where(
                Reaction.message_id == message_id
            )
        )
    ).all()
    summary: dict[str, dict] = {}
    for emoji, author_id in rows:
        entry = summary.setdefault(
            emoji, {"count": 0, "authors": []}
        )
        entry["count"] += 1
        entry["authors"].append(str(author_id))
    return summary


async def reply_count(
    session: AsyncSession, message_id: uuid.UUID
) -> int:
    return (
        await session.scalar(
            select(func.count()).select_from(Message).where(
                Message.parent_id == message_id
            )
        )
    ) or 0


async def message_detail(
    session: AsyncSession, message: Message
) -> dict:
    """Full message view: base fields + reactions, reply count, mentions, quoted parent."""
    data = await message_to_dict(message)
    mentions = parse_mentions(message.content)
    data["mentions"] = [str(m) for m in mentions]
    data["reactions"] = await reaction_summary(session, message.id)
    data["reply_count"] = await reply_count(session, message.id)
    data["quote"] = None
    if message.parent_id is not None:
        parent = await session.get(Message, message.parent_id)
        if parent is not None:
            data["quote"] = {
                "id": str(parent.id),
                "author_id": str(parent.author_id),
                "content": parent.content,
            }
    return data
