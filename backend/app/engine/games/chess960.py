"""Fischer Random Chess (Chess960) using python-chess's variant rules.

The match seed selects one of the 960 legal mirrored back-rank positions. The
selection is stable across reset and replay: ``position = seed % 960``. An
administrator may instead choose an exact ``chess960_position`` or custom FEN.

Actions use the same advertised UCI dictionaries as Chess. For castling,
python-chess's Chess960 UCI convention moves the king to the participating
rook's starting square (for example ``b1h1``); the king and rook then finish on
g1/f1. Agents should always submit an action returned by ``legal_actions``.
"""

from __future__ import annotations

import chess
from pydantic import Field

from app.engine.games.chess import Chess, ChessConfig


class Chess960Config(ChessConfig):
    """Strict administrator-controlled Fischer Random configuration."""

    chess960_position: int | None = Field(default=None, ge=0, le=959)


class Chess960(Chess):
    name = "chess960"
    game_title = "Fischer Random Chess"
    CATALOG = {
        "title": game_title,
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Chess960 with seeded starting positions and full variant castling rules.",
    }
    CONFIG_MODEL = Chess960Config
    CONFIG_DEFAULTS = Chess960Config().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        fen = self.config.get("start_fen")
        if fen:
            try:
                self.board = chess.Board(fen, chess960=True)
            except ValueError as exc:
                raise ValueError(f"invalid start_fen: {exc}") from exc
            self.chess960_position = self.board.chess960_pos()
        else:
            configured_position = self.config.get("chess960_position")
            self.chess960_position = (
                configured_position if configured_position is not None else self.seed % 960
            )
            self.board = chess.Board.from_chess960_pos(self.chess960_position)

        self.pgn_initial_fen = self.board.shredder_fen()
        self.pgn_variant = "Chess960"
        self.move_count = 0
        self.last_move: dict | None = None
        if hasattr(self, "_clock_remaining_ms"):
            self._initialize_clock()

    def get_render_data(self) -> dict:
        render = super().get_render_data()
        render["chess960_position"] = self.chess960_position
        return render

    def observe(self, perspective: int | None = None) -> dict:
        observation = super().observe(perspective)
        observation["state"]["chess960_position"] = self.chess960_position
        return observation
