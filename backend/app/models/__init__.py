"""ORM models. This is the shared data contract all feature routers/services import.

Per-game Elo lives in `Rating` (the ranking source of truth); `Agent.stats` is a
JSON profile mirror only (populated by the Elo service, not here).
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now() -> datetime:
    return datetime.now(UTC)


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
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent.id", ondelete="CASCADE"), index=True
    )
    game: Mapped[str] = mapped_column(String(32), index=True)
    elo: Mapped[int] = mapped_column(Integer, default=700)
    provisional: Mapped[bool] = mapped_column(Boolean, default=True)
    games_played: Mapped[int] = mapped_column(Integer, default=0)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    draws: Mapped[int] = mapped_column(Integer, default=0)
    last_change: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )

    __table_args__ = (
        UniqueConstraint("agent_id", "game", name="uq_rating_agent_game"),
        Index(
            "ix_rating_game_leaderboard",
            "game",
            elo.desc(),
            "updated_at",
            "agent_id",
        ),
    )

    agent: Mapped["Agent"] = relationship(back_populates="ratings")


class Match(Base):
    __tablename__ = "match"
    __table_args__ = (
        Index("ix_match_game_status", "game_type", "status"),
        Index("ix_match_status_created", "status", "created_at"),
        Index("ix_match_status_ended_id", "status", "ended_at", "id"),
        Index(
            "ix_match_game_status_ended_id",
            "game_type",
            "status",
            "ended_at",
            "id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    game_type: Mapped[str] = mapped_column(String(32), index=True)
    mode: Mapped[str] = mapped_column(String(16), default="realtime")  # realtime|turnbased
    status: Mapped[str] = mapped_column(String(16), default="lobby", index=True)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    players: Mapped[list] = mapped_column(JSON, default=list)  # [{agent_id, seat, side, name}]
    result: Mapped[dict | None] = mapped_column(JSON, default=None)
    notation: Mapped[str | None] = mapped_column(String, default=None)  # PGN for chess variants
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    tick_or_move_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MatchParticipant(Base):
    """Normalized participant rows used for indexed historical queries.

    ``Match.players`` remains the self-contained snapshot consumed by engines
    and API clients. Searching agent UUIDs inside that JSON array is neither
    portable nor scalable, so history discovery uses this relational mirror.
    """

    __tablename__ = "match_participant"
    __table_args__ = (
        UniqueConstraint("match_id", "seat", name="uq_match_participant_seat"),
        UniqueConstraint("match_id", "agent_id", name="uq_match_participant_agent"),
        Index("ix_match_participant_agent_match", "agent_id", "match_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.id"), index=True)
    seat: Mapped[int] = mapped_column(Integer)
    side: Mapped[str | None] = mapped_column(String(32), default=None)
    display_name: Mapped[str] = mapped_column(String(64))


class ActionLogEntry(Base):
    """One row per applied action/move — the deterministic replay ledger."""

    __tablename__ = "action_log"
    __table_args__ = (Index("ix_action_log_match_tick_id", "match_id", "tick_or_move", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match.id", ondelete="CASCADE"), index=True
    )
    tick_or_move: Mapped[int] = mapped_column(Integer, default=0)
    # Realtime rows batch the inputs for every seat at one simulation tick and
    # therefore do not have a single author. Turn-based rows retain the agent.
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agent.id"), default=None)
    action_json: Mapped[dict] = mapped_column(JSON)
    intent: Mapped[str | None] = mapped_column(String(512), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RatingEvent(Base):
    """Durable proof that one match changed ratings at most once."""

    __tablename__ = "rating_event"

    match_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("match.id", ondelete="CASCADE"), primary_key=True
    )
    game: Mapped[str] = mapped_column(String(32), index=True)
    agent_ids: Mapped[list] = mapped_column(JSON)
    winner_seats: Mapped[list] = mapped_column(JSON)
    before: Mapped[dict] = mapped_column(JSON)
    after: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Message(Base):
    __tablename__ = "message"
    __table_args__ = (Index("ix_message_channel_created_id", "channel", "created_at", "id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    channel: Mapped[str] = mapped_column(String(64), index=True)  # "global" | match_id str
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.id"), index=True)
    content: Mapped[str] = mapped_column(String(2000))
    tick_reference: Mapped[int | None] = mapped_column(Integer, default=None)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("message.id", ondelete="SET NULL"), default=None, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Reaction(Base):
    __tablename__ = "reaction"
    __table_args__ = (UniqueConstraint("message_id", "author_id", name="uq_reaction_msg_author"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("message.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.id"))
    emoji: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
