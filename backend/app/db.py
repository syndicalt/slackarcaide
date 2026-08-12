"""Async SQLAlchemy engine, declarative Base, and session dependency.

Supports both Postgres (asyncpg) and SQLite (aiosqlite), selected by the
DATABASE_URL scheme. SQLite is convenient for local dev/tests.
"""
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_sessionmaker = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _sessionmaker


async def init_db() -> None:
    """Create tables if they don't exist (v1; no alembic yet)."""
    import app.models  # noqa: F401  (ensure all models are registered)

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session():
    """FastAPI dependency yielding an AsyncSession."""
    async with get_sessionmaker()() as session:
        yield session


async def recover_interrupted_matches() -> None:
    """Mark matches stranded in 'running' by a process restart as 'error'.

    Engine state is in-memory (MatchManager), so after a restart no running
    match can ever resume or finish; without this sweep they ghost the lobby
    and accept joins forever. Imported lazily to avoid a models<->db cycle.
    """
    import logging

    from sqlalchemy import update

    from app.models import Match

    log = logging.getLogger(__name__)
    async with get_sessionmaker()() as session:
        result = await session.execute(
            update(Match)
            .where(Match.status == "running")
            .values(status="error", ended_at=datetime.now(timezone.utc))
        )
        await session.commit()
        if result.rowcount:
            log.warning("recovered %d interrupted match(es) -> error", result.rowcount)
