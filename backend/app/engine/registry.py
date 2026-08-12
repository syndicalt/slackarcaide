"""Game engine registry — the single place that maps a `game_type` string to an
engine class. New games register here (and in the /games catalog) to activate."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.base import BaseGame

from app.engine.games.pong import Pong
from app.engine.games.connect_four import ConnectFour
from app.engine.games.snake import Snake
from app.engine.games.breakout import Breakout
from app.engine.games.tetris import Tetris
from app.engine.games.asteroids import Asteroids
from app.engine.games.chess import Chess
from app.engine.games.checkers import Checkers
from app.engine.games.go import Go

REGISTRY: dict[str, type[BaseGame]] = {
    Pong.name: Pong,
    ConnectFour.name: ConnectFour,
    Snake.name: Snake,
    Breakout.name: Breakout,
    Tetris.name: Tetris,
    Asteroids.name: Asteroids,
    Chess.name: Chess,
    Checkers.name: Checkers,
    Go.name: Go,
}

# /games catalog — DERIVED from REGISTRY so the served catalog and registered
# engines can never drift. Add a game by (1) importing its class and (2) adding
# it to REGISTRY; its CATALOG metadata on the class drives the /games payload.
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
