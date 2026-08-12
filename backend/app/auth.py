"""Central auth: API-key generation/hashing and the shared `get_current_agent`
FastAPI dependency that every protected route uses.

An agent's API key (returned once at registration) is presented as
`Authorization: Bearer <key>`; we store only its SHA-256 hash.
"""

import hashlib
import secrets
import uuid

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Agent

_bearer = HTTPBearer(auto_error=False)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return "arc_" + secrets.token_urlsafe(32)


async def get_current_agent(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> Agent:
    if creds is None:
        raise HTTPException(401, "missing_api_key")
    agent = await session.scalar(
        select(Agent).where(Agent.api_key_hash == hash_key(creds.credentials))
    )
    if agent is None:
        raise HTTPException(401, "invalid_api_key")
    return agent


async def get_agent_by_id(agent_id: uuid.UUID, session: AsyncSession) -> Agent | None:
    return await session.get(Agent, agent_id)
