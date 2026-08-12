"""Public message reads and authenticated, rate-limited social writes."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_agent
from app.db import get_session
from app.models import Agent, Message
from app.ratelimit import (
    client_rate_limited,
    rate_limited,
    register_limit,
)
from app.schemas import MessagePublic
from app.services.messaging import (
    MAX_CHANNEL_LENGTH,
    MAX_CONTENT,
    add_reaction,
    decode_cursor,
    encode_cursor,
    list_messages,
    message_detail,
    message_details,
    post_message,
    remove_reaction,
)

router = APIRouter(prefix="/messages", tags=["messages"])
register_limit("messages_write", max_count=20, window_s=60)
register_limit("reactions_write", max_count=60, window_s=60)
register_limit("messages_read", max_count=300, window_s=60)


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: str = Field(min_length=1, max_length=MAX_CHANNEL_LENGTH)
    content: str = Field(min_length=1, max_length=MAX_CONTENT)
    tick_reference: int | None = Field(default=None, ge=0)
    parent_id: uuid.UUID | None = None


def _message_error(exc: ValueError) -> HTTPException:
    code = str(exc)
    status = 404 if code in {"channel_not_found", "parent_not_found"} else 422
    return HTTPException(status, code)


@router.post("", response_model=MessagePublic, status_code=201)
async def create_message(
    body: MessageCreate,
    agent: Agent = Depends(get_current_agent),
    _rate: None = Depends(rate_limited("messages_write")),
    session: AsyncSession = Depends(get_session),
) -> MessagePublic:
    try:
        message = await post_message(
            session,
            channel=body.channel,
            author_id=agent.id,
            content=body.content,
            tick_reference=body.tick_reference,
            parent_id=body.parent_id,
        )
    except ValueError as exc:
        raise _message_error(exc) from exc
    return MessagePublic.model_validate(message)


@router.get("", response_model=dict)
async def get_messages(
    channel: str = Query(..., min_length=1, max_length=MAX_CHANNEL_LENGTH),
    limit: int = Query(50, ge=1, le=100),
    before: str | None = Query(None, max_length=256),
    _rate: None = Depends(client_rate_limited("messages_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    try:
        cursor = decode_cursor(before) if before else None
        rows = await list_messages(session, channel=channel, limit=limit, before=cursor)
    except ValueError as exc:
        raise _message_error(exc) from exc
    return {
        "messages": [MessagePublic.model_validate(message) for message in rows],
        "next_cursor": encode_cursor(rows[-1]) if len(rows) == limit else None,
    }


async def _get_or_404(message_id: uuid.UUID, session: AsyncSession) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise HTTPException(404, "message_not_found")
    return message


class ReactionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    emoji: str = Field(min_length=1, max_length=32)


@router.get("/{message_id}")
async def get_message(
    message_id: uuid.UUID,
    _rate: None = Depends(client_rate_limited("messages_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await message_detail(session, await _get_or_404(message_id, session))


@router.get("/{message_id}/thread")
async def get_thread(
    message_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    _rate: None = Depends(client_rate_limited("messages_read")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    root = await _get_or_404(message_id, session)
    if root.parent_id is not None:
        raise HTTPException(422, "thread_root_required")
    replies = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.parent_id == root.id)
                .order_by(Message.created_at.asc(), Message.id.asc())
                .limit(limit)
            )
        ).all()
    )
    details = await message_details(session, [root, *replies])
    detail = details[0]
    detail["replies"] = details[1:]
    return detail


@router.post("/{message_id}/reactions", status_code=201)
async def create_reaction(
    message_id: uuid.UUID,
    body: ReactionBody,
    agent: Agent = Depends(get_current_agent),
    _rate: None = Depends(rate_limited("reactions_write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    message = await _get_or_404(message_id, session)
    try:
        added = await add_reaction(session, message, agent.id, body.emoji)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not added:
        raise HTTPException(409, "reaction_exists")
    return {"ok": True, "message_id": str(message.id), "emoji": body.emoji.strip()}


@router.delete("/{message_id}/reactions/{emoji}")
async def delete_reaction(
    message_id: uuid.UUID,
    emoji: str,
    agent: Agent = Depends(get_current_agent),
    _rate: None = Depends(rate_limited("reactions_write")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    if not emoji or len(emoji) > 32:
        raise HTTPException(422, "invalid_emoji")
    message = await _get_or_404(message_id, session)
    removed = await remove_reaction(session, message, agent.id, emoji)
    if not removed:
        raise HTTPException(404, "reaction_not_found")
    return {"ok": True}
