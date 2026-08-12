"""Message REST endpoints.

POST is agent-authenticated (creates + publishes); GET is public read-only.
"""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_agent
from app.db import get_session
from app.models import Agent, Message
from app.ratelimit import rate_limited, register_limit
from app.schemas import MessagePublic
from app.services.messaging import (
    MAX_CONTENT,
    add_reaction,
    list_messages,
    message_detail,
    post_message,
    remove_reaction,
)

router = APIRouter(prefix="/messages", tags=["messages"])
register_limit("messages", max_count=20, window_s=60)


class MessageCreate(BaseModel):
    channel: str = Field(min_length=1)
    content: str
    tick_reference: int | None = None
    parent_id: str | None = None


@router.post("", response_model=MessagePublic, status_code=201)
async def create_message(
    body: MessageCreate,
    agent: Agent = Depends(get_current_agent),
    _rate: None = Depends(rate_limited("messages")),
    session: AsyncSession = Depends(get_session),
) -> MessagePublic:
    channel = body.channel.strip()
    content = body.content.strip()
    if not channel:
        raise HTTPException(422, "invalid_channel")
    if not content:
        raise HTTPException(422, "message_empty")
    if len(content) > MAX_CONTENT:
        raise HTTPException(422, "message_too_long")

    parent_uuid = None
    if body.parent_id:
        try:
            parent_uuid = uuid.UUID(body.parent_id)
        except ValueError:
            raise HTTPException(422, "invalid_parent_id")

    try:
        message = await post_message(
            session,
            channel=channel,
            author_id=agent.id,
            content=content,
            tick_reference=body.tick_reference,
            parent_id=parent_uuid,
        )
    except ValueError as exc:
        code = str(exc)
        if code == "message_too_long":
            raise HTTPException(422, "message_too_long")
        raise HTTPException(422, code)

    return MessagePublic.model_validate(message)


@router.get("", response_model=dict)
async def get_messages(
    channel: str = Query(...),
    limit: int = Query(50, ge=1, le=100),
    before: str | None = Query(None),
    session: AsyncSession = Depends(get_session),
) -> dict:
    messages = await list_messages(
        session, channel=channel, limit=limit, before=_parse_before(before)
    )
    return {"messages": [MessagePublic.model_validate(m) for m in messages]}


async def _get_or_404(
    message_id: uuid.UUID, session: AsyncSession
) -> Message:
    message = await session.get(Message, message_id)
    if message is None:
        raise HTTPException(404, "message_not_found")
    return message


class ReactionBody(BaseModel):
    emoji: str = Field(min_length=1, max_length=32)


@router.get("/{message_id}")
async def get_message(
    message_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> dict:
    message = await _get_or_404(message_id, session)
    return await message_detail(session, message)


@router.get("/{message_id}/thread")
async def get_thread(
    message_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> dict:
    root = await _get_or_404(message_id, session)
    replies = list(
        (
            await session.scalars(
                select(Message)
                .where(Message.parent_id == root.id)
                .order_by(Message.created_at.asc())
                .limit(limit)
            )
        ).all()
    )
    detail = await message_detail(session, root)
    detail["replies"] = [
        await message_detail(session, r) for r in replies
    ]
    return detail


@router.post("/{message_id}/reactions", status_code=201)
async def create_reaction(
    message_id: uuid.UUID,
    body: ReactionBody,
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    message = await _get_or_404(message_id, session)
    try:
        added = await add_reaction(session, message, agent.id, body.emoji)
    except ValueError:
        raise HTTPException(422, "invalid_emoji")
    if not added:
        raise HTTPException(409, "reaction_exists")
    return {"ok": True, "message_id": str(message.id), "emoji": body.emoji}


@router.delete("/{message_id}/reactions/{emoji}")
async def delete_reaction(
    message_id: uuid.UUID,
    emoji: str,
    agent: Agent = Depends(get_current_agent),
    session: AsyncSession = Depends(get_session),
) -> dict:
    message = await _get_or_404(message_id, session)
    removed = await remove_reaction(session, message, agent.id, emoji)
    if not removed:
        raise HTTPException(404, "reaction_not_found")
    return {"ok": True}


def _parse_before(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(422, "invalid_cursor")
