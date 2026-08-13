"""Production game registry.

Only engines present in :data:`REGISTRY` are served in the catalog, accepted by
the match API, eligible for ratings, or available to replay. Keeping this as an
explicit allowlist makes production activation an intentional code change.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.base import BaseGame

from app.engine.games.battleship import Battleship
from app.engine.games.bomberman import Bomberman
from app.engine.games.checkers import Checkers
from app.engine.games.chess import Chess
from app.engine.games.chess960 import Chess960
from app.engine.games.connect_four import ConnectFour
from app.engine.games.go import Go
from app.engine.games.last_server import LastServer
from app.engine.games.pong import Pong
from app.engine.games.reversi import Reversi
from app.engine.games.tetris import Tetris
from app.engine.games.tron import Tron
from app.engine.games.ultimate_ttt import UltimateTicTacToe

REGISTRY: dict[str, type[BaseGame]] = {
    Chess.name: Chess,
    Chess960.name: Chess960,
    ConnectFour.name: ConnectFour,
    Reversi.name: Reversi,
    Checkers.name: Checkers,
    Go.name: Go,
    Pong.name: Pong,
    Tron.name: Tron,
    UltimateTicTacToe.name: UltimateTicTacToe,
    Battleship.name: Battleship,
    Bomberman.name: Bomberman,
    Tetris.name: Tetris,
    LastServer.name: LastServer,
}


def normalize_game_config(game_type: str, config: dict | None) -> dict:
    """Return canonical trusted config or raise for a disabled/invalid game."""
    engine = REGISTRY.get(game_type)
    if engine is None:
        raise KeyError(game_type)
    return engine.normalize_config(config)


# The public catalog is derived from the production allowlist.  Enabling an
# engine therefore requires an intentional registry change and cannot happen by
# accidentally importing an experimental module.
GAMES_CATALOG: list[dict] = [
    {
        "game": cls.name,
        "mode": cls.mode,
        "name": cls.CATALOG["title"],
        "players": {
            "min": cls.CATALOG["min_players"],
            "max": cls.CATALOG["max_players"],
        },
        "players_before_start": cls.CATALOG["players_before_start"],
        "elo_ranked": bool(cls.CATALOG["elo_ranked"]),
        "blurb": cls.CATALOG["blurb"],
    }
    for cls in REGISTRY.values()
]
