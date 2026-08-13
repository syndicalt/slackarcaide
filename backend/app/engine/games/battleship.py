"""Two-player Battleship with private, perspective-scoped observations.

Each player submits their entire fleet in one atomic placement action, in the
canonical ship order declared by :data:`FLEET`. Ships may touch, but may not
overlap or extend beyond the 10x10 board. Seat 0 places first and also fires
first after both fleets are ready.

Placement actions are intentionally not enumerated: the combinatorial action
space would make observations unusable. ``get_legal_actions`` returns one
bounded contract descriptor during placement and ``legal_actions_exhaustive``
advertises that the host must defer membership validation to ``apply_action``.
Fire actions are exhaustively enumerated and have the exact form
``{"row": 0, "column": 0}``.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.base import BaseGame, IllegalMove

BOARD_SIZE = 10
FLEET: tuple[tuple[str, int], ...] = (
    ("carrier", 5),
    ("battleship", 4),
    ("cruiser", 3),
    ("submarine", 3),
    ("destroyer", 2),
)

type _Coordinate = tuple[int, int]
type _Fleet = dict[str, tuple[_Coordinate, ...]]


class BattleshipTimeControl(BaseModel):
    """Admin-controlled Fischer clock settings."""

    model_config = ConfigDict(extra="forbid", strict=True)

    base_sec: int = Field(default=600, ge=1, le=86_400)
    increment_sec: int = Field(default=3, ge=0, le=3_600)
    enabled: bool = True


class BattleshipConfig(BaseModel):
    """The intentionally fixed standard Battleship ruleset."""

    model_config = ConfigDict(extra="forbid", strict=True)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    board_size: Literal[10] = 10
    ships_may_touch: Literal[True] = True
    time_control: BattleshipTimeControl = Field(default_factory=BattleshipTimeControl)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


class Battleship(BaseGame):
    mode = "turnbased"
    name = "battleship"
    CATALOG = {
        "title": "Battleship",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Place a hidden fleet, then locate and sink every enemy ship.",
    }
    CONFIG_MODEL = BattleshipConfig
    CONFIG_DEFAULTS = BattleshipConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.phase: Literal["placement", "battle"] = "placement"
        self.turn = 0
        self.move_count = 0
        self.fleets: list[_Fleet | None] = [None, None]
        # shots[attacker][coordinate] is "hit" or "miss".
        self.shots: list[dict[_Coordinate, str]] = [{}, {}]
        self.last_move: dict[str, Any] | None = None
        self._end_reason: str | None = None
        if hasattr(self, "_clock_remaining_ms"):
            self._initialize_clock()

    def current_seat(self) -> int:
        return self.turn

    def legal_actions_exhaustive(self, seat: int) -> bool:
        """Whether the host may enforce membership in ``get_legal_actions``."""

        return self.phase != "placement" or seat != self.current_seat()

    @staticmethod
    def _placement_contract() -> dict[str, Any]:
        return {
            "$contract": "complete_fleet",
            "submit": {
                "ships": [
                    {
                        "id": ship_id,
                        "length": length,
                        "start": {"row": "integer 0..9", "column": "integer 0..9"},
                        "orientation": ["horizontal", "vertical"],
                    }
                    for ship_id, length in FLEET
                ]
            },
            "canonical_order_required": True,
            "ships_may_touch": True,
        }

    def get_legal_actions(self, seat: int) -> list[dict[str, Any]]:
        if (
            self.is_terminal()
            or isinstance(seat, bool)
            or not isinstance(seat, int)
            or seat != self.current_seat()
        ):
            return []
        if self.phase == "placement":
            return [self._placement_contract(), {"resign": True}]

        actions: list[dict[str, Any]] = [
            {"row": row, "column": column}
            for row in range(BOARD_SIZE)
            for column in range(BOARD_SIZE)
            if (row, column) not in self.shots[seat]
        ]
        actions.append({"resign": True})
        return actions

    @staticmethod
    def _coordinate(row: Any, column: Any) -> _Coordinate:
        if (
            isinstance(row, bool)
            or not isinstance(row, int)
            or isinstance(column, bool)
            or not isinstance(column, int)
        ):
            raise IllegalMove("invalid_coordinate", "row and column must be integers from 0 to 9")
        if not 0 <= row < BOARD_SIZE or not 0 <= column < BOARD_SIZE:
            raise IllegalMove("invalid_coordinate", "row and column must be integers from 0 to 9")
        return row, column

    @classmethod
    def _validated_fleet(cls, action: Any) -> _Fleet:
        if not isinstance(action, dict) or set(action) != {"ships"}:
            raise IllegalMove("invalid_action", "placement must contain exactly 'ships'")
        ships = action["ships"]
        if not isinstance(ships, list) or len(ships) != len(FLEET):
            raise IllegalMove("invalid_fleet", f"ships must contain exactly {len(FLEET)} entries")

        fleet: _Fleet = {}
        occupied: set[_Coordinate] = set()
        for index, (expected_id, length) in enumerate(FLEET):
            ship = ships[index]
            if not isinstance(ship, dict) or set(ship) != {"id", "start", "orientation"}:
                raise IllegalMove(
                    "invalid_ship", "each ship must contain exactly id, start, and orientation"
                )
            if ship["id"] != expected_id:
                raise IllegalMove(
                    "invalid_ship_order", f"ship {index} must be the {expected_id}"
                )
            start = ship["start"]
            if not isinstance(start, dict) or set(start) != {"row", "column"}:
                raise IllegalMove("invalid_ship", "start must contain exactly row and column")
            row, column = cls._coordinate(start["row"], start["column"])
            orientation = ship["orientation"]
            if orientation not in ("horizontal", "vertical") or not isinstance(orientation, str):
                raise IllegalMove(
                    "invalid_orientation", "orientation must be 'horizontal' or 'vertical'"
                )

            row_step, column_step = (0, 1) if orientation == "horizontal" else (1, 0)
            cells = tuple(
                (row + offset * row_step, column + offset * column_step)
                for offset in range(length)
            )
            if any(not (0 <= r < BOARD_SIZE and 0 <= c < BOARD_SIZE) for r, c in cells):
                raise IllegalMove("ship_out_of_bounds", f"{expected_id} extends beyond the board")
            if occupied.intersection(cells):
                raise IllegalMove("ships_overlap", f"{expected_id} overlaps another ship")
            occupied.update(cells)
            fleet[expected_id] = cells
        return fleet

    @staticmethod
    def _validated_battle_action(action: Any) -> _Coordinate | None:
        if not isinstance(action, dict):
            raise IllegalMove("invalid_action", "action must be a shot or {'resign': true}")
        if set(action) == {"resign"}:
            if action["resign"] is True:
                return None
            raise IllegalMove("invalid_action", "resign must be true")
        if set(action) != {"row", "column"}:
            raise IllegalMove("invalid_action", "a shot must contain exactly row and column")
        return Battleship._coordinate(action["row"], action["column"])

    def validate_action(self, action: Any, seat: int) -> None:
        """Validate an action synchronously without changing engine state."""

        if self.is_terminal():
            raise IllegalMove("game_over", "game already ended")
        if (
            isinstance(seat, bool)
            or not isinstance(seat, int)
            or seat not in (0, 1)
            or seat != self.current_seat()
        ):
            raise IllegalMove("out_of_turn", "action is not for the current seat")
        remaining = self.clock_ms(seat)
        if remaining is not None and remaining <= 0:
            raise IllegalMove("clock_expired", "clock expired before action")

        if isinstance(action, dict) and set(action) == {"resign"}:
            if action["resign"] is True:
                return
            raise IllegalMove("invalid_action", "resign must be true")
        if self.phase == "placement":
            self._validated_fleet(action)
            return

        coordinate = self._validated_battle_action(action)
        if coordinate is not None and coordinate in self.shots[seat]:
            raise IllegalMove("duplicate_shot", "that coordinate has already been fired upon")

    def apply_action(self, action: Any) -> None:
        seat = self.current_seat()
        self.validate_action(action, seat)

        if isinstance(action, dict) and set(action) == {"resign"}:
            self._note_move(seat)
            self._end_reason = "resignation"
            self.last_move = {"event": "resign", "seat": seat, "move": self.move_count}
            self._set_result([1 - seat])
            return

        if self.phase == "placement":
            # Fully validate into local immutable tuples before committing anything.
            fleet = self._validated_fleet(action)
            self.fleets[seat] = fleet
            self.last_move = {
                "event": "fleet_placed",
                "seat": seat,
                "move": self.move_count + 1,
            }
            if seat == 0:
                self.turn = 1
            else:
                self.phase = "battle"
                self.turn = 0
            self._note_move(seat)
            return

        coordinate = self._validated_battle_action(action)
        if coordinate is None:  # handled above, retained for type narrowing
            raise AssertionError("resignation must be handled before battle validation")
        defender = 1 - seat
        defender_fleet = self.fleets[defender]
        if defender_fleet is None:  # unreachable through the public state machine
            raise RuntimeError("battle phase started without both fleets")
        ship_id = next(
            (candidate for candidate, cells in defender_fleet.items() if coordinate in cells),
            None,
        )
        outcome = "hit" if ship_id is not None else "miss"
        self.shots[seat][coordinate] = outcome
        sunk_ship = ship_id if ship_id is not None and self._is_sunk(defender, ship_id) else None
        won = all(self._is_sunk(defender, candidate) for candidate, _length in FLEET)
        self.turn = defender
        self.last_move = {
            "event": "fire",
            "seat": seat,
            "row": coordinate[0],
            "column": coordinate[1],
            "outcome": outcome,
            "sunk": sunk_ship,
            "move": self.move_count + 1,
        }
        self._note_move(seat)
        if won:
            self._end_reason = "fleet_sunk"
            self._set_result([seat])

    def _is_sunk(self, defender: int, ship_id: str) -> bool:
        fleet = self.fleets[defender]
        if fleet is None:
            return False
        attacker = 1 - defender
        return all(self.shots[attacker].get(cell) == "hit" for cell in fleet[ship_id])

    def _ship_records(self, defender: int) -> list[dict[str, Any]]:
        fleet = self.fleets[defender]
        if fleet is None:
            return []
        attacker = 1 - defender
        return [
            {
                "id": ship_id,
                "length": len(cells),
                "cells": [
                    {
                        "row": row,
                        "column": column,
                        "hit": self.shots[attacker].get((row, column)) == "hit",
                    }
                    for row, column in cells
                ],
                "sunk": self._is_sunk(defender, ship_id),
            }
            for ship_id, cells in fleet.items()
        ]

    def _board_records(self, perspective: int | None) -> list[dict[str, Any]]:
        reveal_all = self.is_terminal()
        boards: list[dict[str, Any]] = []
        for defender in (0, 1):
            attacker = 1 - defender
            cells = [
                {"row": row, "column": column, "shot": outcome}
                for (row, column), outcome in sorted(self.shots[attacker].items())
            ]
            board: dict[str, Any] = {"seat": defender, "cells": cells}
            if self.fleets[defender] is not None and (reveal_all or perspective == defender):
                board["ships"] = self._ship_records(defender)
            boards.append(board)
        return boards

    def get_scores(self) -> dict[str, Any]:
        return {
            "shots": [len(entries) for entries in self.shots],
            "hits": [
                sum(outcome == "hit" for outcome in entries.values()) for entries in self.shots
            ],
            "misses": [
                sum(outcome == "miss" for outcome in entries.values()) for entries in self.shots
            ],
            "ships_sunk": [
                sum(self._is_sunk(1 - attacker, ship_id) for ship_id, _length in FLEET)
                for attacker in (0, 1)
            ],
            "fleets_placed": [fleet is not None for fleet in self.fleets],
        }

    def get_render_data(self) -> dict[str, Any]:
        """Return a public-safe board; fleets appear only after termination."""

        return {
            "size": BOARD_SIZE,
            "phase": self.phase,
            "turn": self.current_seat(),
            "boards": self._board_records(None),
            "fleets_placed": [fleet is not None for fleet in self.fleets],
            "last_move": deepcopy(self.last_move),
            "terminal": self.is_terminal(),
        }

    def summary(self) -> str:
        if self.is_terminal():
            winner = self.get_winner()
            if winner is None:
                return "Battleship — draw"
            reason = " by resignation" if self._end_reason == "resignation" else ""
            return f"Battleship — player {winner[0]} wins{reason}"
        if self.phase == "placement":
            return f"Battleship — player {self.turn} must place a complete fleet"
        return f"Battleship — player {self.turn} to fire"

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        if perspective is not None and (
            isinstance(perspective, bool)
            or not isinstance(perspective, int)
            or perspective not in (0, 1)
        ):
            raise ValueError("perspective must be seat 0, seat 1, or None")
        legal_actions = (
            self.get_legal_actions(self.current_seat())
            if perspective is None or perspective == self.current_seat()
            else []
        )
        return {
            "state": {
                "size": BOARD_SIZE,
                "phase": self.phase,
                "turn": self.current_seat(),
                "boards": self._board_records(perspective),
                "fleets_placed": [fleet is not None for fleet in self.fleets],
                "perspective": perspective,
            },
            "legal_actions": legal_actions,
            "legal_actions_exhaustive": self.legal_actions_exhaustive(self.current_seat()),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": deepcopy(self.last_move),
            "time": self.clock_state(),
        }
