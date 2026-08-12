"""Seed Fischer Random rating rows for agents registered before activation."""

import sqlalchemy as sa
from alembic import op

revision = "0003_chess960_ratings"
down_revision = "0002_hardened_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO rating "
            "(agent_id, game, elo, provisional, games_played, wins, losses, draws, "
            "last_change, updated_at) "
            "SELECT agent.id, 'chess960', 700, TRUE, 0, 0, 0, 0, 0, CURRENT_TIMESTAMP "
            "FROM agent WHERE NOT EXISTS ("
            "SELECT 1 FROM rating "
            "WHERE rating.agent_id = agent.id AND rating.game = 'chess960')"
        )
    )


def downgrade() -> None:
    raise RuntimeError(
        "0003 is intentionally irreversible: activated Chess960 ratings may contain match history"
    )
