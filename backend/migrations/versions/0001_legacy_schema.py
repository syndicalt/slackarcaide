"""Create the legacy schema that predates Alembic."""

import sqlalchemy as sa
from alembic import op

revision = "0001_legacy_schema"
down_revision = None
branch_labels = None
depends_on = None


_LEGACY_COLUMNS = {
    "agent": {
        "id",
        "display_name",
        "bio",
        "avatar_url",
        "api_key_hash",
        "created_at",
        "last_seen",
        "stats",
    },
    "match": {
        "id",
        "game_type",
        "mode",
        "status",
        "config",
        "seed",
        "players",
        "result",
        "notation",
        "started_at",
        "ended_at",
        "tick_or_move_count",
        "created_at",
    },
    "rating": {
        "id",
        "agent_id",
        "game",
        "elo",
        "provisional",
        "games_played",
        "wins",
        "losses",
        "draws",
        "last_change",
        "updated_at",
    },
    "action_log": {
        "id",
        "match_id",
        "tick_or_move",
        "agent_id",
        "action_json",
        "intent",
        "created_at",
    },
    "message": {
        "id",
        "channel",
        "author_id",
        "content",
        "tick_reference",
        "parent_id",
        "created_at",
    },
    "reaction": {"id", "message_id", "author_id", "emoji", "created_at"},
}

_LEGACY_UNIQUES = {
    "rating": {"uq_rating_agent_game": ("agent_id", "game")},
    "reaction": {
        "uq_reaction_msg_author_emoji": ("message_id", "author_id", "emoji")
    },
}


def _adopt_exact_legacy_schema() -> bool:
    """Return true only for the known pre-Alembic schema.

    The first Railway deployment predates Alembic and created these tables from
    ORM metadata. Refusing partial or shape-mismatched schemas prevents an
    automatic stamp from concealing drift or a failed historical deployment.
    """
    inspector = sa.inspect(op.get_bind())
    existing = set(inspector.get_table_names()) & set(_LEGACY_COLUMNS)
    if not existing:
        return False
    if existing != set(_LEGACY_COLUMNS):
        missing = sorted(set(_LEGACY_COLUMNS) - existing)
        raise RuntimeError(f"partial legacy schema; missing tables: {missing}")

    for table, expected_columns in _LEGACY_COLUMNS.items():
        actual_columns = {column["name"] for column in inspector.get_columns(table)}
        if actual_columns != expected_columns:
            raise RuntimeError(
                f"legacy schema mismatch for {table}: expected {sorted(expected_columns)}, "
                f"found {sorted(actual_columns)}"
            )

    for table, expected_constraints in _LEGACY_UNIQUES.items():
        actual_constraints = {
            constraint["name"]: tuple(constraint["column_names"])
            for constraint in inspector.get_unique_constraints(table)
            if constraint["name"] is not None
        }
        for name, columns in expected_constraints.items():
            if actual_constraints.get(name) != columns:
                raise RuntimeError(
                    f"legacy schema mismatch for {table}: missing unique constraint {name}"
                )
    return True


def upgrade() -> None:
    if _adopt_exact_legacy_schema():
        return

    op.create_table(
        "agent",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.String(64), nullable=False),
        sa.Column("bio", sa.String(512)),
        sa.Column("avatar_url", sa.String(512)),
        sa.Column("api_key_hash", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("api_key_hash"),
    )
    op.create_index("ix_agent_display_name", "agent", ["display_name"], unique=True)
    op.create_table(
        "match",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("game_type", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("players", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("notation", sa.String()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("tick_or_move_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_match_game_type", "match", ["game_type"])
    op.create_index("ix_match_status", "match", ["status"])
    op.create_table(
        "rating",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("game", sa.String(32), nullable=False),
        sa.Column("elo", sa.Integer(), nullable=False),
        sa.Column("provisional", sa.Boolean(), nullable=False),
        sa.Column("games_played", sa.Integer(), nullable=False),
        sa.Column("wins", sa.Integer(), nullable=False),
        sa.Column("losses", sa.Integer(), nullable=False),
        sa.Column("draws", sa.Integer(), nullable=False),
        sa.Column("last_change", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id", "game", name="uq_rating_agent_game"),
    )
    op.create_index("ix_rating_agent_id", "rating", ["agent_id"])
    op.create_index("ix_rating_game", "rating", ["game"])
    op.create_table(
        "action_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("tick_or_move", sa.Integer(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("action_json", sa.JSON(), nullable=False),
        sa.Column("intent", sa.String(512)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["match_id"], ["match.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_action_log_match_id", "action_log", ["match_id"])
    op.create_table(
        "message",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.String(2000), nullable=False),
        sa.Column("tick_reference", sa.Integer()),
        sa.Column("parent_id", sa.Uuid()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["agent.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_message_author_id", "message", ["author_id"])
    op.create_index("ix_message_channel", "message", ["channel"])
    op.create_table(
        "reaction",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("emoji", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_id"], ["agent.id"]),
        sa.ForeignKeyConstraint(["message_id"], ["message.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "message_id", "author_id", "emoji", name="uq_reaction_msg_author_emoji"
        ),
    )
    op.create_index("ix_reaction_message_id", "reaction", ["message_id"])


def downgrade() -> None:
    for table in ("reaction", "message", "action_log", "rating", "match", "agent"):
        op.drop_table(table)
