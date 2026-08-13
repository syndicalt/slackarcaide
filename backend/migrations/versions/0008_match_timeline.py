"""Add typed public chat and safe match-operation projections."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_match_timeline"
down_revision = "0007_match_seed_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("message") as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=16),
                server_default="chat",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("topic", sa.String(length=32), nullable=True))
    with op.batch_alter_table("action_log") as batch_op:
        batch_op.add_column(sa.Column("public_event", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("action_log") as batch_op:
        batch_op.drop_column("public_event")
    with op.batch_alter_table("message") as batch_op:
        batch_op.drop_column("topic")
        batch_op.drop_column("kind")
