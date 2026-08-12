"""Validation for the public realtime subscription namespace."""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db import get_sessionmaker
from app.models import Match


def normalize_channel(value: object) -> str | None:
    """Return a canonical public channel name, or ``None`` when it is invalid."""
    if not isinstance(value, str) or len(value) > 80:
        return None
    if value in {"lobby", "messages:global"}:
        return value

    if value.startswith("match:"):
        prefix = "match:"
    elif value.startswith("messages:"):
        prefix = "messages:"
    else:
        return None

    try:
        identifier = uuid.UUID(value.removeprefix(prefix))
    except (ValueError, AttributeError):
        return None
    return f"{prefix}{identifier}"


async def channels_exist(channels: set[str]) -> bool:
    """Reject arbitrary UUID channels that would inflate Redis subscriptions."""
    match_ids = {
        uuid.UUID(channel.split(":", 1)[1])
        for channel in channels
        if channel not in {"lobby", "messages:global"}
    }
    if not match_ids:
        return True
    async with get_sessionmaker()() as session:
        existing = set(
            (await session.scalars(select(Match.id).where(Match.id.in_(match_ids)))).all()
        )
    return existing == match_ids
