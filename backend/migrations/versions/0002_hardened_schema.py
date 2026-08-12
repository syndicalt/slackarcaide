"""Add replay, rating-audit, messaging, and query-integrity constraints."""

import sqlalchemy as sa
from alembic import op

revision = "0002_hardened_schema"
down_revision = "0001_legacy_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("action_log") as batch:
        batch.alter_column("agent_id", existing_type=sa.Uuid(), nullable=True)
        batch.create_index("ix_action_log_match_tick_id", ["match_id", "tick_or_move", "id"])

    op.create_table(
        "rating_event",
        sa.Column("match_id", sa.Uuid(), nullable=False),
        sa.Column("game", sa.String(32), nullable=False),
        sa.Column("agent_ids", sa.JSON(), nullable=False),
        sa.Column("winner_seats", sa.JSON(), nullable=False),
        sa.Column("before", sa.JSON(), nullable=False),
        sa.Column("after", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["match.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("match_id"),
    )
    op.create_index("ix_rating_event_game", "rating_event", ["game"])

    # Legacy rows had no parent foreign key. Preserve valid root replies and
    # detach dangling, cross-channel, nested, self, or cyclic references before
    # adding the constraint and enforcing the same invariant in the service.
    op.execute(
        sa.text(
            "UPDATE message SET parent_id = NULL WHERE parent_id IS NOT NULL AND ("
            "parent_id NOT IN (SELECT id FROM message) OR id IN ("
            "SELECT child.id FROM message AS child JOIN message AS parent "
            "ON child.parent_id = parent.id WHERE parent.parent_id IS NOT NULL "
            "OR child.channel <> parent.channel))"
        )
    )
    with op.batch_alter_table("message") as batch:
        batch.create_foreign_key(
            "fk_message_parent_id_message", "message", ["parent_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_message_parent_id", ["parent_id"])
        batch.create_index("ix_message_channel_created_id", ["channel", "created_at", "id"])

    op.execute(
        sa.text(
            "DELETE FROM reaction WHERE id NOT IN "
            "(SELECT MIN(id) FROM reaction GROUP BY message_id, author_id)"
        )
    )
    with op.batch_alter_table("reaction") as batch:
        batch.drop_constraint("uq_reaction_msg_author_emoji", type_="unique")
        batch.create_unique_constraint("uq_reaction_msg_author", ["message_id", "author_id"])

    op.create_index(
        "ix_rating_game_leaderboard",
        "rating",
        ["game", sa.text("elo DESC"), "updated_at", "agent_id"],
    )
    op.create_index("ix_match_game_status", "match", ["game_type", "status"])
    op.create_index("ix_match_status_created", "match", ["status", "created_at"])


def downgrade() -> None:
    raise RuntimeError(
        "0002 is intentionally irreversible: realtime action rows have no single agent, "
        "and restoring the legacy reaction constraint would require inventing or deleting data"
    )
