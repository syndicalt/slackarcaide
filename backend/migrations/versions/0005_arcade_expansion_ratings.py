"""Seed rating rows for the competitive arcade expansion."""

import sqlalchemy as sa
from alembic import op

revision = "0005_arcade_expansion_ratings"
down_revision = "0004_add_board_game_ratings"
branch_labels = None
depends_on = None

_GAMES = ("tron", "ultimate_ttt", "battleship", "bomberman", "tetris")


def upgrade() -> None:
    statement = sa.text(
        "INSERT INTO rating "
        "(agent_id, game, elo, provisional, games_played, wins, losses, draws, "
        "last_change, updated_at) "
        "SELECT agent.id, :game, 700, TRUE, 0, 0, 0, 0, 0, CURRENT_TIMESTAMP "
        "FROM agent WHERE NOT EXISTS ("
        "SELECT 1 FROM rating "
        "WHERE rating.agent_id = agent.id AND rating.game = :game)"
    )
    for game in _GAMES:
        op.execute(statement.bindparams(game=game))


def downgrade() -> None:
    raise RuntimeError(
        "0005 is intentionally irreversible: activated game ratings may contain match history"
    )
