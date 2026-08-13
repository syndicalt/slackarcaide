"""Store the full validated 63-bit deterministic match seed."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_match_seed_bigint"
down_revision = "0006_match_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("match") as batch_op:
        batch_op.alter_column(
            "seed",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("match") as batch_op:
        batch_op.alter_column(
            "seed",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
