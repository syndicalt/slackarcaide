"""Agents + auth API. Registration returns an API key exactly once; all
protected endpoints authenticate via `Authorization: Bearer <key>`.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import generate_api_key, get_agent_by_id, get_current_agent, hash_key
from app.db import get_session
from app.models import Agent, Rating
from app.ratelimit import client_rate_limited, rate_limited, register_limit
from app.schemas import AgentPublic, AgentRegister
from app.services.ratings import seed_initial_ratings

router = APIRouter(prefix="/agents", tags=["agents"])
auth_router = APIRouter(prefix="/auth", tags=["auth"])
register_limit("registration", max_count=20, window_s=3600)
register_limit("token_exchange", max_count=60, window_s=60)
register_limit("agent_read", max_count=3_600, window_s=60)


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1, max_length=256)


@auth_router.post("/token")
async def create_token(
    body: TokenRequest,
    _rate: None = Depends(client_rate_limited("token_exchange")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Exchange a raw API key for the owning agent's id."""
    agent = await session.scalar(select(Agent).where(Agent.api_key_hash == hash_key(body.api_key)))
    if agent is None:
        raise HTTPException(401, "invalid_api_key")
    return {"agent_id": str(agent.id), "ok": True}


@router.post("/register", response_model=None)
async def register(
    body: AgentRegister,
    _rate: None = Depends(client_rate_limited("registration")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Create an agent and return its API key (shown only once)."""
    existing = await session.scalar(select(Agent).where(Agent.display_name == body.display_name))
    if existing is not None:
        raise HTTPException(409, "agent_display_name_taken")

    api_key = generate_api_key()
    agent = Agent(
        display_name=body.display_name,
        bio=body.bio,
        avatar_url=body.avatar_url,
        api_key_hash=hash_key(api_key),
        stats={},
    )
    session.add(agent)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(409, "agent_display_name_taken") from exc
    await seed_initial_ratings(session, agent)
    await session.commit()
    return {"agent": AgentPublic.model_validate(agent), "api_key": api_key}


@router.get("/me", response_model=AgentPublic)
async def me(
    _rate: None = Depends(rate_limited("agent_read")),
    agent: Agent = Depends(get_current_agent),
) -> AgentPublic:
    return AgentPublic.model_validate(agent)


@router.get("/{agent_id}", response_model=AgentPublic)
async def get_agent(
    agent_id: uuid.UUID,
    _rate: None = Depends(client_rate_limited("agent_read")),
    session: AsyncSession = Depends(get_session),
) -> AgentPublic:
    agent = await get_agent_by_id(agent_id, session)
    if agent is None:
        raise HTTPException(404, "agent_not_found")
    return AgentPublic.model_validate(agent)


@router.get("/{agent_id}/ratings")
async def get_agent_ratings(
    agent_id: uuid.UUID,
    _rate: None = Depends(client_rate_limited("agent_read")),
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Per-game Elo rows for the agent (empty list if none)."""
    if await get_agent_by_id(agent_id, session) is None:
        raise HTTPException(404, "agent_not_found")
    rows = (await session.scalars(select(Rating).where(Rating.agent_id == agent_id))).all()
    return [
        {
            "game": r.game,
            "elo": r.elo,
            "provisional": r.provisional,
            "games_played": r.games_played,
            "wins": r.wins,
            "losses": r.losses,
            "draws": r.draws,
            "last_change": r.last_change,
            "updated_at": r.updated_at,
        }
        for r in rows
    ]
