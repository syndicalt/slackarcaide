"""Async SQLAlchemy engine, declarative Base, and session dependency.

Supports both Postgres (asyncpg) and SQLite (aiosqlite), selected by the
DATABASE_URL scheme. SQLite is convenient for local dev/tests.
"""

from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_sessionmaker = None


def _migration_head() -> str:
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    revision = ScriptDirectory.from_config(config).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic migration history has no head revision")
    return revision


EXPECTED_SCHEMA_REVISION = _migration_head()


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        options = {"pool_pre_ping": True}
        if settings.database_url.startswith("postgresql"):
            options.update(
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=10,
                connect_args={"timeout": 5, "command_timeout": 30},
            )
        _engine = create_async_engine(settings.database_url, **options)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _sessionmaker


async def init_db() -> None:
    """Initialize disposable SQLite or verify a migrated production schema.

    Tests use in-memory SQLite and deliberately create their schema from ORM
    metadata. PostgreSQL is deployment state: mutating it with ``create_all``
    would bypass Alembic and make later upgrades ambiguous, so startup fails
    closed unless the expected revision is already installed.
    """
    import app.models  # noqa: F401  (ensure all models are registered)

    settings = get_settings()
    async with get_engine().begin() as conn:
        if settings.database_url.startswith("sqlite"):
            await conn.run_sync(Base.metadata.create_all)
            return
        revision = await conn.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != EXPECTED_SCHEMA_REVISION:
            raise RuntimeError(
                "database schema is not current: "
                f"expected {EXPECTED_SCHEMA_REVISION!r}, found {revision!r}; "
                "run `alembic upgrade head` before starting the API"
            )


async def get_session():
    """FastAPI dependency yielding an AsyncSession."""
    async with get_sessionmaker()() as session:
        yield session


async def close_db() -> None:
    """Dispose pooled connections and reset lazy globals for clean shutdown."""
    global _engine, _sessionmaker
    engine = _engine
    _sessionmaker = None
    _engine = None
    if engine is not None:
        await engine.dispose()


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
            .values(status="error", ended_at=datetime.now(UTC))
        )
        await session.commit()
        if result.rowcount:
            log.warning("recovered %d interrupted match(es) -> error", result.rowcount)
