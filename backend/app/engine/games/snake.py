"""Snake — realtime multiplayer engine (spec §8).

Server-authoritative and deterministic given `(config, seed, seats)` (all
randomness flows through `self.rng`). Supports 1-4 players. Each alive seat
submits `{"direction": "up"|"down"|"left"|"right"}` per tick; a missing/invalid
action keeps the snake coasting (documented noop). The snake moves one cell per
tick in its current direction, reverses are ignored, eating the single food cell
grows it and scores a point, and hitting the wall, another snake, or itself kills
that lane. `is_terminal` when every snake is dead; the winner is the survivors'
seat indices (empty list on a full wipe).
"""
from typing import Any

from app.engine.base import BaseGame, IllegalMove

_DIR = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}


class Snake(BaseGame):
    mode = "realtime"
    name = "snake"
    CATALOG = {
        "title": "Snake",
        "min_players": 1,
        "max_players": 2,
        "players_before_start": 1,
        "elo_ranked": True,
        "blurb": "Grow your snake; run rivals into your tail.",
    }
    CONFIG_DEFAULTS = {
        "cols": 19,
        "rows": 21,
        "players": 2,
        "players_before_start": 1,
    }

    def reset(self) -> None:
        self.tick = 0
        self.cols = int(self.config["cols"])
        self.rows = int(self.config["rows"])
        self.n = len(self.seats)
        self.snakes: list[dict] = []
        self._init_snakes()
        self.food: list[int] | None = self._spawn_food()
        self.scores: dict[int, int] = {i: 0 for i in range(self.n)}
        self.last_move = None

    def _init_snakes(self) -> None:
        """Place each snake with head at row mid-column and body extending left."""
        base = self.rows // 2
        spread = max(1, self.n - 1)
        head_col = max(3, self.cols // 3)
        for i in range(self.n):
            row = base - spread + 2 * i
            segments = [[row, head_col], [row, head_col - 1], [row, head_col - 2]]
            self.snakes.append({
                "seat": i,
                "alive": True,
                "segments": segments,
                "direction": "right",
            })

    def _occupied_cells(self) -> set[tuple[int, int]]:
        cells: set[tuple[int, int]] = set()
        for s in self.snakes:
            if s["alive"]:
                for seg in s["segments"]:
                    cells.add((seg[0], seg[1]))
        return cells

    def _spawn_food(self) -> list[int] | None:
        occupied = self._occupied_cells()
        free = [(r, c) for r in range(self.rows) for c in range(self.cols)
                if (r, c) not in occupied]
        if not free:
            return None
        r, c = self.rng.choice(free)
        return [int(r), int(c)]

    @staticmethod
    def _is_reverse(cur: str, nxt: str) -> bool:
        dr, dc = _DIR[cur]
        nr, nc = _DIR[nxt]
        return (dr + nr, dc + nc) == (0, 0)

    def _kill(self, seat: int) -> None:
        for s in self.snakes:
            if s["seat"] == seat:
                s["alive"] = False
                break
        self.last_move = {"event": "crash", "seat": seat}

    # ---- realtime ---------------------------------------------------------
    def step(self, moves: dict[int, Any]) -> None:
        self.tick += 1

        # 1. apply queued directions (ignore reverses / invalid / dead).
        for s in self.snakes:
            if not s["alive"]:
                continue
            mv = moves.get(s["seat"])
            if isinstance(mv, dict):
                d = mv.get("direction")
                if d in _DIR and not self._is_reverse(s["direction"], d):
                    s["direction"] = d

        if all(not s["alive"] for s in self.snakes):
            return

        food_cell = tuple(self.food) if self.food is not None else None

        # 2. compute next heads; wall deaths drop out.
        heads: dict[int, tuple[int, int]] = {}
        grow_seats: set[int] = set()
        for s in self.snakes:
            if not s["alive"]:
                continue
            dr, dc = _DIR[s["direction"]]
            r, c = s["segments"][0]
            nr, nc = r + dr, c + dc
            if not (0 <= nr < self.rows and 0 <= nc < self.cols):
                self._kill(s["seat"])
                continue
            heads[s["seat"]] = (nr, nc)
            if food_cell is not None and (nr, nc) == food_cell:
                grow_seats.add(s["seat"])

        # 3. occupancy of the pre-move board; non-growing snakes vacate their tail.
        occupied: set[tuple[int, int]] = set()
        for s in self.snakes:
            if not s["alive"]:
                continue
            body = s["segments"]
            cells = body if s["seat"] in grow_seats else body[:-1]
            for seg in cells:
                occupied.add((seg[0], seg[1]))

        # 4. resolve moves in seat order.
        for s in self.snakes:
            seat = s["seat"]
            if seat not in heads:
                continue
            nh = heads[seat]
            # head-on into another snake targeting the same cell kills both.
            head_on = any(os != seat and oh == nh for os, oh in heads.items())
            if nh in occupied or head_on:
                self._kill(seat)
                continue
            if seat not in grow_seats:
                tail = s["segments"].pop()
                occupied.discard((tail[0], tail[1]))
            s["segments"].insert(0, [nh[0], nh[1]])
            occupied.add((nh[0], nh[1]))
            if seat in grow_seats:
                self.scores[seat] = self.scores.get(seat, 0) + 1

        # 5. respawn food if a surviving snake reached it.
        if food_cell is not None:
            reached = any(
                s["alive"] and tuple(s["segments"][0]) == food_cell
                for s in self.snakes
            )
            if reached:
                self.food = self._spawn_food()

    # ---- shared -----------------------------------------------------------
    def is_terminal(self) -> bool:
        return all(not s["alive"] for s in self.snakes)

    def get_winner(self) -> list[int] | None:
        if not self.is_terminal():
            return None
        return [s["seat"] for s in self.snakes if s["alive"]]

    def get_scores(self) -> dict:
        return dict(self.scores)

    def get_legal_actions(self, seat: int) -> list[dict]:
        return [{"direction": d} for d in _DIR]

    def get_render_data(self) -> dict:
        return {
            "w": self.cols,
            "h": self.rows,
            "snakes": [
                {"seat": s["seat"], "segments": s["segments"], "alive": s["alive"]}
                for s in self.snakes
            ],
            "food": self.food,
            "scores": self.scores,
        }

    def observe(self, perspective: int | None = None) -> dict:
        return {
            "state": {
                "w": self.cols,
                "h": self.rows,
                "snakes": [
                    {"seat": s["seat"], "segments": s["segments"], "alive": s["alive"]}
                    for s in self.snakes
                ],
                "food": self.food,
            },
            "legal_actions": [list(self.get_legal_actions(i)) for i in range(self.n)],
            "scores": dict(self.scores),
            "summary": self.summary(),
            "last_move": self.last_move,
            "time": None,
        }

    def summary(self) -> str:
        alive = [s["seat"] for s in self.snakes if s["alive"]]
        if not alive:
            return f"Snake over — no survivors (scores {self.scores})"
        parts = ", ".join(f"P{seat}:{self.scores[seat]}" for seat in alive)
        return f"Snake tick {self.tick} — alive [{parts}]"


CATALOG = {
    "game": "snake",
    "mode": "realtime",
    "name": "Snake",
    "players": {"min": 1, "max": 4},
    "players_before_start": 1,
    "elo_ranked": False,
    "blurb": "Eat food, don't crash.",
}
