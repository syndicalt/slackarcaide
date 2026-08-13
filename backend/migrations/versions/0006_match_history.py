"""Add normalized participant history and terminal-history query indexes."""

from __future__ import annotations

import json
import uuid
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "0006_match_history"
down_revision = "0005_arcade_expansion_ratings"
branch_labels = None
depends_on = None


def _players(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return (
        [player for player in value if isinstance(player, dict)] if isinstance(value, list) else []
    )


def upgrade() -> None:
    op.create_index("ix_match_status_ended_id", "match", ["status", "ended_at", "id"])
    op.create_index(
        "ix_match_game_status_ended_id",
        "match",
        ["game_type", "status", "ended_at", "id"],
    )
    op.create_table(
        "match_participant",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("seat", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(32), nullable=True),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["match_id"], ["match.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", "agent_id", name="uq_match_participant_agent"),
        sa.UniqueConstraint("match_id", "seat", name="uq_match_participant_seat"),
    )
    op.create_index("ix_match_participant_agent_id", "match_participant", ["agent_id"])
    op.create_index("ix_match_participant_match_id", "match_participant", ["match_id"])
    op.create_index(
        "ix_match_participant_agent_match",
        "match_participant",
        ["agent_id", "match_id"],
    )

    bind = op.get_bind()
    participant = sa.table(
        "match_participant",
        sa.column("match_id", sa.Uuid()),
        sa.column("agent_id", sa.Uuid()),
        sa.column("seat", sa.Integer()),
        sa.column("side", sa.String()),
        sa.column("display_name", sa.String()),
    )
    known_agents = {str(row[0]) for row in bind.execute(sa.text("SELECT id FROM agent"))}
    cursor = bind.execute(sa.text('SELECT id, players FROM "match"'))
    while rows := cursor.fetchmany(500):
        batch: list[dict[str, Any]] = []
        for match_id, raw_players in rows:
            try:
                normalized_match_id = uuid.UUID(str(match_id))
            except (ValueError, TypeError, AttributeError):
                continue
            seen_agents: set[uuid.UUID] = set()
            seen_seats: set[int] = set()
            for player in _players(raw_players):
                raw_agent_id = str(player.get("agent_id", ""))
                try:
                    agent_id = uuid.UUID(raw_agent_id)
                    seat = int(player["seat"])
                except (ValueError, TypeError, KeyError, AttributeError):
                    continue
                if raw_agent_id not in known_agents and agent_id.hex not in known_agents:
                    continue
                if agent_id in seen_agents or seat in seen_seats:
                    continue
                seen_agents.add(agent_id)
                seen_seats.add(seat)
                name = player.get("name")
                batch.append(
                    {
                        "match_id": normalized_match_id,
                        "agent_id": agent_id,
                        "seat": seat,
                        "side": str(player["side"])[:32] if player.get("side") else None,
                        "display_name": str(name)[:64] if name else raw_agent_id[:64],
                    }
                )
        if batch:
            bind.execute(participant.insert(), batch)


def downgrade() -> None:
    op.drop_table("match_participant")
    op.drop_index("ix_match_game_status_ended_id", table_name="match")
    op.drop_index("ix_match_status_ended_id", table_name="match")
