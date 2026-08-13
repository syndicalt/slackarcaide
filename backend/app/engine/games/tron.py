"""Deterministic two-player Tron / Light Cycles.

Both riders choose a relative turn simultaneously on every tick. Accepted
actions are exactly ``{"turn": "left"|"straight"|"right"}``. A missing or
malformed action is deliberately treated as ``straight``: realtime packet
loss or client garbage must not crash or stall the authoritative match loop.

The grid is discrete and every occupied cell is permanent. Collision
resolution is simultaneous: walls, either existing trail, a shared target
cell, and swapping head cells all crash the affected rider. If both riders
crash on the same tick the result is a draw, regardless of collision reason.
"""

from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from app.engine.base import BaseGame

DEFAULT_WIDTH = 41
DEFAULT_HEIGHT = 31
MIN_DIMENSION = 9
MAX_DIMENSION = 101

_DIRECTION_NAMES = ("north", "east", "south", "west")
_DIRECTION_VECTORS = ((0, -1), (1, 0), (0, 1), (-1, 0))
_TURN_OFFSETS = {"left": -1, "straight": 0, "right": 1}


class TronConfig(BaseModel):
    """Server-controlled Light Cycles rules with hard resource bounds."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    width: int = Field(default=DEFAULT_WIDTH, ge=MIN_DIMENSION, le=MAX_DIMENSION)
    height: int = Field(default=DEFAULT_HEIGHT, ge=MIN_DIMENSION, le=MAX_DIMENSION)
    tick_rate: int = Field(default=10, ge=2, le=60)
    max_ticks: int = Field(default=2_500, ge=1, le=10_000)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


class Tron(BaseGame):
    mode = "realtime"
    name = "tron"
    CATALOG = {
        "title": "Tron / Light Cycles",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Turn, claim space, and trap the opposing light cycle without hitting a trail.",
    }
    CONFIG_MODEL = TronConfig
    CONFIG_DEFAULTS = TronConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.rng.seed(self.seed)
        self.tick = 0
        self.move_count = 0

        width = int(self.config["width"])
        middle_row = int(self.config["height"]) // 2
        left_column = width // 4
        right_column = width - 1 - left_column

        # Mirror-image starts with equal space behind and ahead. Riders face
        # one another; no seed can silently confer a positional advantage.
        self.heads: list[tuple[int, int]] = [
            (left_column, middle_row),
            (right_column, middle_row),
        ]
        self.directions: list[int] = [1, 3]  # east, west
        self.trails: list[list[tuple[int, int]]] = [[self.heads[0]], [self.heads[1]]]
        self._occupied: set[tuple[int, int]] = {self.heads[0], self.heads[1]}
        self.alive = [True, True]
        self.crashes: list[dict[str, Any]] = []
        self.last_move: dict[str, Any] | None = None

    @staticmethod
    def _parse_turn(action: Any) -> Literal["left", "straight", "right"]:
        """Return a safe relative turn; all invalid shapes become straight."""
        if not isinstance(action, dict) or set(action) != {"turn"}:
            return "straight"
        turn = action.get("turn")
        if isinstance(turn, str) and turn in _TURN_OFFSETS:
            return cast(Literal["left", "straight", "right"], turn)
        return "straight"

    def step(self, moves: dict[int, Any]) -> None:
        if self.is_terminal():
            return
        submitted = moves if isinstance(moves, dict) else {}
        turns = [self._parse_turn(submitted.get(seat)) for seat in (0, 1)]
        next_directions = [
            (self.directions[seat] + _TURN_OFFSETS[turns[seat]]) % 4 for seat in (0, 1)
        ]
        targets = [
            (
                self.heads[seat][0] + _DIRECTION_VECTORS[next_directions[seat]][0],
                self.heads[seat][1] + _DIRECTION_VECTORS[next_directions[seat]][1],
            )
            for seat in (0, 1)
        ]

        reasons: list[list[str]] = [[], []]
        width = int(self.config["width"])
        height = int(self.config["height"])
        for seat, (column, row) in enumerate(targets):
            if not (0 <= column < width and 0 <= row < height):
                reasons[seat].append("wall")
            if (column, row) in self._occupied:
                reasons[seat].append("trail")

        if targets[0] == targets[1]:
            reasons[0].append("head_on")
            reasons[1].append("head_on")
        if targets[0] == self.heads[1] and targets[1] == self.heads[0]:
            reasons[0].append("crossing")
            reasons[1].append("crossing")

        crashed = [bool(reasons[0]), bool(reasons[1])]
        # Turns happen even when the following movement crashes. This makes
        # the terminal frame faithfully show the direction each rider chose.
        self.directions = next_directions
        for seat in (0, 1):
            if not crashed[seat]:
                self.heads[seat] = targets[seat]
                self.trails[seat].append(targets[seat])
                self._occupied.add(targets[seat])

        self.tick += 1
        self.move_count = self.tick
        self.alive = [not crashed[0], not crashed[1]]
        self.crashes = [
            {"seat": seat, "at": [*targets[seat]], "reasons": reasons[seat].copy()}
            for seat in (0, 1)
            if crashed[seat]
        ]
        self.last_move = {
            "tick": self.tick,
            "turns": turns.copy(),
            "targets": [[*target] for target in targets],
            "crashes": [dict(crash, reasons=crash["reasons"].copy()) for crash in self.crashes],
        }

        if crashed[0] and crashed[1]:
            self._set_result(None)
        elif crashed[0]:
            self._set_result([1])
        elif crashed[1]:
            self._set_result([0])
        elif self.tick >= int(self.config["max_ticks"]):
            self._set_result(None)

    def get_legal_actions(self, seat: int) -> list[dict[str, str]]:
        if self.is_terminal() or seat not in (0, 1):
            return []
        return [{"turn": turn} for turn in ("left", "straight", "right")]

    def get_scores(self) -> dict[str, Any]:
        return {
            "trail_cells": [len(self.trails[0]), len(self.trails[1])],
            "survival_ticks": self.tick,
            "alive": self.alive.copy(),
        }

    def get_render_data(self) -> dict[str, Any]:
        return {
            "width": int(self.config["width"]),
            "height": int(self.config["height"]),
            "trails": [[[x, y] for x, y in trail] for trail in self.trails],
            "heads": [[x, y] for x, y in self.heads],
            "directions": [_DIRECTION_NAMES[direction] for direction in self.directions],
            "alive": self.alive.copy(),
            "crashes": [
                {
                    "seat": crash["seat"],
                    "at": crash["at"].copy(),
                    "reasons": crash["reasons"].copy(),
                }
                for crash in self.crashes
            ],
            "tick": self.tick,
            "max_ticks": int(self.config["max_ticks"]),
        }

    def summary(self) -> str:
        if not self.is_terminal():
            return f"Light Cycles — tick {self.tick} of {self.config['max_ticks']}"
        winner = self.get_winner()
        if winner is None:
            reason = "simultaneous crash" if self.crashes else "tick-limit draw"
            return f"Light Cycles — {reason}"
        loser = 1 - winner[0]
        return f"Light Cycles — player {loser} crashes; player {winner[0]} wins"

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        return {
            "state": {
                "width": int(self.config["width"]),
                "height": int(self.config["height"]),
                "heads": [[x, y] for x, y in self.heads],
                "directions": [_DIRECTION_NAMES[direction] for direction in self.directions],
                "trails": [[[x, y] for x, y in trail] for trail in self.trails],
                "alive": self.alive.copy(),
                "tick": self.tick,
                "max_ticks": int(self.config["max_ticks"]),
            },
            "legal_actions": [self.get_legal_actions(seat) for seat in (0, 1)],
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": (
                {
                    "tick": self.last_move["tick"],
                    "turns": self.last_move["turns"].copy(),
                    "targets": [target.copy() for target in self.last_move["targets"]],
                    "crashes": [
                        {
                            "seat": crash["seat"],
                            "at": crash["at"].copy(),
                            "reasons": crash["reasons"].copy(),
                        }
                        for crash in self.last_move["crashes"]
                    ],
                }
                if self.last_move
                else None
            ),
            "time": None,
        }
