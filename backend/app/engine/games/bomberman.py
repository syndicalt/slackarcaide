"""Deterministic, server-authoritative two-player Bomberman Duel.

Each realtime tick accepts exactly ``{"move": direction, "bomb": bool}``, where
``direction`` is ``up``, ``down``, ``left``, ``right``, or ``noop``. Missing or
malformed actions become ``{"move": "noop", "bomb": False}``; client garbage
must never terminate the match loop.

Tick ordering is deliberately explicit: expire old flames, place bombs at the
players' starting cells, resolve movement simultaneously, tick/explode bombs,
apply all flame damage simultaneously, then collect safe powerups. Bombs block
entry but never prevent a player already sharing their cell from leaving or
waiting. Solid walls stop blasts; a crate is destroyed by and stops its ray.
Bombs chain immediately and do not stop rays.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.engine.base import BaseGame

DEFAULT_WIDTH = 13
DEFAULT_HEIGHT = 11
MIN_DIMENSION = 9
MAX_DIMENSION = 25

Position = tuple[int, int]
Move = Literal["up", "down", "left", "right", "noop"]
Powerup = Literal["capacity", "range"]

_MOVES: tuple[Move, ...] = ("up", "down", "left", "right", "noop")
_VECTORS: dict[Move, Position] = {
    "up": (0, -1),
    "down": (0, 1),
    "left": (-1, 0),
    "right": (1, 0),
    "noop": (0, 0),
}
_RAYS: tuple[Position, ...] = ((0, -1), (1, 0), (0, 1), (-1, 0))


class BombermanConfig(BaseModel):
    """Server-controlled rules with strict CPU, memory, and duration bounds."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    players_required: Literal[2] = 2
    max_players: Literal[2] = 2
    ranked: bool = True
    width: int = Field(default=DEFAULT_WIDTH, ge=MIN_DIMENSION, le=MAX_DIMENSION)
    height: int = Field(default=DEFAULT_HEIGHT, ge=MIN_DIMENSION, le=MAX_DIMENSION)
    tick_rate: int = Field(default=8, ge=2, le=30)
    max_ticks: int = Field(default=2_400, ge=1, le=10_000)
    bomb_fuse_ticks: int = Field(default=16, ge=2, le=120)
    flame_ticks: int = Field(default=4, ge=1, le=30)
    starting_capacity: int = Field(default=1, ge=1, le=8)
    starting_range: int = Field(default=2, ge=1, le=8)
    max_capacity: int = Field(default=8, ge=1, le=12)
    max_blast_range: int = Field(default=8, ge=1, le=12)
    crate_density: float = Field(default=0.48, ge=0, le=0.85)
    powerup_chance: float = Field(default=0.4, ge=0, le=1)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)

    @model_validator(mode="after")
    def validate_board_and_limits(self) -> BombermanConfig:
        if self.width % 2 == 0 or self.height % 2 == 0:
            raise ValueError("width and height must be odd")
        if self.starting_capacity > self.max_capacity:
            raise ValueError("starting_capacity must not exceed max_capacity")
        if self.starting_range > self.max_blast_range:
            raise ValueError("starting_range must not exceed max_blast_range")
        return self


@dataclass(slots=True)
class Bomb:
    owner: int
    fuse: int
    blast_range: int


class Bomberman(BaseGame):
    mode = "realtime"
    name = "bomberman"
    CATALOG = {
        "title": "Bomberman Duel",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Plant bombs, chain explosions, and outmaneuver your opponent in a tight arena.",
    }
    CONFIG_MODEL = BombermanConfig
    CONFIG_DEFAULTS = BombermanConfig().model_dump(mode="python")

    def reset(self) -> None:
        self._terminal = False
        self._winner = None
        self.rng.seed(self.seed)
        self.tick = 0
        self.move_count = 0

        width = int(self.config["width"])
        height = int(self.config["height"])
        self.solid_walls: set[Position] = {
            (x, y)
            for y in range(height)
            for x in range(width)
            if x in (0, width - 1) or y in (0, height - 1) or (x % 2 == 0 and y % 2 == 0)
        }
        self.positions: list[Position] = [(1, 1), (width - 2, height - 2)]
        self.alive = [True, True]
        self.capacities = [int(self.config["starting_capacity"])] * 2
        self.blast_ranges = [int(self.config["starting_range"])] * 2
        self.active_bombs = [0, 0]
        self.bombs: dict[Position, Bomb] = {}
        self.flames: dict[Position, int] = {}
        self.powerups: dict[Position, Powerup] = {}
        self._hidden_powerups: dict[Position, Powerup] = {}
        self.crates: set[Position] = set()
        self.last_move: dict[str, Any] | None = None
        self._generate_mirrored_crates()

    def _mirror(self, position: Position) -> Position:
        return (
            int(self.config["width"]) - 1 - position[0],
            int(self.config["height"]) - 1 - position[1],
        )

    def _generate_mirrored_crates(self) -> None:
        width = int(self.config["width"])
        height = int(self.config["height"])
        safe: set[Position] = {
            (1, 1),
            (2, 1),
            (1, 2),
            (width - 2, height - 2),
            (width - 3, height - 2),
            (width - 2, height - 3),
        }
        density = float(self.config["crate_density"])
        chance = float(self.config["powerup_chance"])

        candidates = [
            (x, y)
            for y in range(1, height - 1)
            for x in range(1, width - 1)
            if (x, y) not in self.solid_walls and (x, y) not in safe
        ]
        visited: set[Position] = set()
        for position in candidates:
            if position in visited:
                continue
            mirrored = self._mirror(position)
            orbit = {position, mirrored}
            visited.update(orbit)
            if self.rng.random() >= density:
                continue
            self.crates.update(orbit)
            if self.rng.random() < chance:
                kind: Powerup = "capacity" if self.rng.randrange(2) == 0 else "range"
                for cell in orbit:
                    self._hidden_powerups[cell] = kind

    @staticmethod
    def _parse_action(action: Any) -> tuple[Move, bool]:
        """Validate the exact bounded action shape, or return a safe noop."""
        if not isinstance(action, dict) or set(action) != {"move", "bomb"}:
            return ("noop", False)
        move = action.get("move")
        bomb = action.get("bomb")
        if not isinstance(move, str) or move not in _VECTORS or not isinstance(bomb, bool):
            return ("noop", False)
        return (cast(Move, move), bomb)

    def _can_place_bomb(self, seat: int) -> bool:
        return (
            self.alive[seat]
            and self.active_bombs[seat] < self.capacities[seat]
            and self.positions[seat] not in self.bombs
        )

    def _age_flames(self) -> None:
        self.flames = {
            position: remaining - 1 for position, remaining in self.flames.items() if remaining > 1
        }

    def _place_bombs(self, actions: list[tuple[Move, bool]]) -> list[dict[str, Any]]:
        placed: list[dict[str, Any]] = []
        for seat, (_, requested) in enumerate(actions):
            if not requested or not self._can_place_bomb(seat):
                continue
            position = self.positions[seat]
            bomb = Bomb(
                owner=seat,
                fuse=int(self.config["bomb_fuse_ticks"]),
                blast_range=self.blast_ranges[seat],
            )
            self.bombs[position] = bomb
            self.active_bombs[seat] += 1
            placed.append({"seat": seat, "at": [*position]})
        return placed

    def _resolve_movement(self, actions: list[tuple[Move, bool]]) -> list[dict[str, Any]]:
        origins = self.positions.copy()
        targets = origins.copy()
        blocked = [False, False]
        for seat, (move, _) in enumerate(actions):
            if not self.alive[seat]:
                continue
            dx, dy = _VECTORS[move]
            candidate = (origins[seat][0] + dx, origins[seat][1] + dy)
            # A bomb blocks entry, but a player may remain on or leave the bomb
            # underneath them. This is essential for useful bomb placement.
            obstacle = (
                candidate in self.solid_walls
                or candidate in self.crates
                or (candidate in self.bombs and candidate != origins[seat])
            )
            if obstacle:
                blocked[seat] = True
            else:
                targets[seat] = candidate

        if all(self.alive) and (
            targets[0] == targets[1] or (targets[0] == origins[1] and targets[1] == origins[0])
        ):
            targets = origins.copy()
            blocked = [True, True]

        self.positions = targets
        return [
            {
                "seat": seat,
                "from": [*origins[seat]],
                "to": [*targets[seat]],
                "blocked": blocked[seat],
            }
            for seat in (0, 1)
        ]

    def _blast_cells(self, origin: Position, blast_range: int) -> set[Position]:
        cells = {origin}
        for dx, dy in _RAYS:
            for distance in range(1, blast_range + 1):
                cell = (origin[0] + dx * distance, origin[1] + dy * distance)
                if cell in self.solid_walls:
                    break
                cells.add(cell)
                if cell in self.crates:
                    break
        return cells

    def _explode_bombs(
        self, newly_placed: set[Position]
    ) -> tuple[list[dict[str, Any]], list[list[int]]]:
        queued: list[Position] = []
        queued_set: set[Position] = set()
        for position, bomb in self.bombs.items():
            if position not in newly_placed:
                bomb.fuse -= 1
            if bomb.fuse <= 0:
                queued.append(position)
                queued_set.add(position)

        explosions: list[dict[str, Any]] = []
        destroyed_crates: set[Position] = set()
        all_blasts: set[Position] = set()
        index = 0
        while index < len(queued):
            origin = queued[index]
            index += 1
            bomb = self.bombs.pop(origin, None)
            if bomb is None:
                continue
            self.active_bombs[bomb.owner] -= 1
            blast = self._blast_cells(origin, bomb.blast_range)
            all_blasts.update(blast)
            crates_hit = blast & self.crates
            destroyed_crates.update(crates_hit)
            explosions.append(
                {
                    "owner": bomb.owner,
                    "at": [*origin],
                    "cells": [[*cell] for cell in sorted(blast)],
                }
            )
            for cell in sorted(blast):
                if cell in self.bombs and cell not in queued_set:
                    queued.append(cell)
                    queued_set.add(cell)

        if not all_blasts:
            return ([], [])

        # Pre-existing exposed upgrades are destroyed by fire. Drops under a
        # crate survive the blast that reveals them and become collectible once
        # its flame expires; a later blast can destroy them normally.
        for cell in all_blasts:
            self.powerups.pop(cell, None)
            self.flames[cell] = max(self.flames.get(cell, 0), int(self.config["flame_ticks"]))
        self.crates.difference_update(destroyed_crates)
        for cell in sorted(destroyed_crates):
            if kind := self._hidden_powerups.pop(cell, None):
                self.powerups[cell] = kind
        return (explosions, [[*cell] for cell in sorted(destroyed_crates)])

    def _collect_powerups(self) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        for seat in (0, 1):
            position = self.positions[seat]
            if not self.alive[seat] or position in self.flames:
                continue
            kind = self.powerups.pop(position, None)
            if kind is None:
                continue
            if kind == "capacity":
                self.capacities[seat] = min(
                    int(self.config["max_capacity"]), self.capacities[seat] + 1
                )
            else:
                self.blast_ranges[seat] = min(
                    int(self.config["max_blast_range"]), self.blast_ranges[seat] + 1
                )
            collected.append({"seat": seat, "at": [*position], "kind": kind})
        return collected

    def step(self, moves: dict[int, Any]) -> None:
        if self.is_terminal():
            return
        submitted = moves if isinstance(moves, dict) else {}
        actions = [self._parse_action(submitted.get(seat)) for seat in (0, 1)]
        self._age_flames()
        placed = self._place_bombs(actions)
        movements = self._resolve_movement(actions)
        explosions, destroyed_crates = self._explode_bombs({tuple(entry["at"]) for entry in placed})

        deaths: list[int] = []
        for seat in (0, 1):
            if self.alive[seat] and self.positions[seat] in self.flames:
                self.alive[seat] = False
                deaths.append(seat)
        collected = self._collect_powerups()

        self.tick += 1
        self.move_count = self.tick
        self.last_move = {
            "tick": self.tick,
            "actions": [{"move": move, "bomb": bomb} for move, bomb in actions],
            "placed": placed,
            "movement": movements,
            "explosions": explosions,
            "destroyed_crates": destroyed_crates,
            "collected": collected,
            "deaths": deaths,
        }

        if len(deaths) == 2:
            self._set_result(None)
        elif deaths:
            self._set_result([1 - deaths[0]])
        elif self.tick >= int(self.config["max_ticks"]):
            self._set_result(None)

    def get_legal_actions(self, seat: int) -> list[dict[str, Any]]:
        if seat not in (0, 1) or self.is_terminal() or not self.alive[seat]:
            return []
        bomb_choices = (False, True) if self._can_place_bomb(seat) else (False,)
        return [{"move": move, "bomb": bomb} for move in _MOVES for bomb in bomb_choices]

    def get_scores(self) -> dict[str, Any]:
        return {
            "alive": self.alive.copy(),
            "survival_ticks": self.tick,
            "capacity": self.capacities.copy(),
            "blast_range": self.blast_ranges.copy(),
            "active_bombs": self.active_bombs.copy(),
        }

    def get_render_data(self) -> dict[str, Any]:
        return {
            "width": int(self.config["width"]),
            "height": int(self.config["height"]),
            "solid_walls": [[*cell] for cell in sorted(self.solid_walls)],
            "crates": [[*cell] for cell in sorted(self.crates)],
            "players": [
                {
                    "seat": seat,
                    "position": [*self.positions[seat]],
                    "alive": self.alive[seat],
                    "capacity": self.capacities[seat],
                    "blast_range": self.blast_ranges[seat],
                    "active_bombs": self.active_bombs[seat],
                }
                for seat in (0, 1)
            ],
            "bombs": [
                {
                    "position": [*position],
                    "owner": bomb.owner,
                    "fuse": bomb.fuse,
                    "blast_range": bomb.blast_range,
                }
                for position, bomb in sorted(self.bombs.items())
            ],
            "flames": [
                {"position": [*position], "remaining": remaining}
                for position, remaining in sorted(self.flames.items())
            ],
            "powerups": [
                {"position": [*position], "kind": kind}
                for position, kind in sorted(self.powerups.items())
            ],
            "tick": self.tick,
            "max_ticks": int(self.config["max_ticks"]),
        }

    def summary(self) -> str:
        if not self.is_terminal():
            return f"Bomberman Duel — tick {self.tick} of {self.config['max_ticks']}"
        winner = self.get_winner()
        if winner is None:
            reason = "simultaneous knockout" if not any(self.alive) else "tick-limit draw"
            return f"Bomberman Duel — {reason}"
        return f"Bomberman Duel — player {winner[0]} survives and wins"

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        render = self.get_render_data()
        return {
            "state": copy.deepcopy(render),
            "legal_actions": [self.get_legal_actions(seat) for seat in (0, 1)],
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": copy.deepcopy(self.last_move),
            "time": None,
        }
