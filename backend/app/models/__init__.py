"""ORM models. This is the shared data contract all feature routers/services import.

Per-game Elo lives in `Rating` (the ranking source of truth); `Agent.stats` is a
JSON profile mirror only (populated by the Elo service, not here).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Agent(Base):
    __tablename__ = "agent"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    bio: Mapped[str | None] = mapped_column(String(512), default=None)
    avatar_url: Mapped[str | None] = mapped_column(String(512), default=None)
    api_key_hash: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
    stats: Mapped[dict] = mapped_column(JSON, default=dict)

    ratings: Mapped[list["Rating"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class Rating(Base):
    """Per-game Elo row. UNIQUE(agent_id, game) is the ranking key."""

    __tablename__ = "rating"
    __table_args__ = (UniqueConstraint("agent_id", "game", name="uq_rating_agent_game"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent.id", ondelete="CASCADE"), index=True
    )
    game: Mapped[str] = mapped_column(String(32), index=True)
    elo: Mapped[int] = mapped_column(Integer, default=1500)
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    last_change: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    agent: Mapped["Agent"] = relationship(back_populates="ratings")


class Match(Base):
    __tablename__ = "match"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    game_type: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="realtime")  # realtime|turnbased
    status: Mapped[str] = mapped_column(String(16), default="lobby", index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    players: Mapped[list] = mapped_column(JSON, default=list)  # [{agent_id, seat, side, name}]
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    notation: Mapped[str | None] = mapped_column(String, default=None)  # PGN for chess
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    tick_or_move_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ActionLogEntry(Base):
    """One row per applied action/move — the deterministic replay ledger."""

    __tablename__ = "action_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match.id", ondelete="CASCADE"), index=True
    )
    tick_or_move: Mapped[int] = mapped_column(Integer, default=0)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.id"))
    action_json: Mapped[dict] = mapped_column(JSON)
    intent: Mapped[str | None] = mapped_column(String(512), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Message(Base):
    __tablename__ = "message"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(64), index=True)  # "global" | match_id str
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.id"), index=True)
    content: Mapped[str] = mapped_column(String(2000))
    tick_reference: Mapped[int | None] = mapped_column(Integer, default=None)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Reaction(Base):
    __tablename__ = "reaction"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "author_id", "emoji", name="uq_reaction_msg_author_emoji"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.id"))
    emoji: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
