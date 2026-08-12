"""Breakout — single-player realtime engine.

One paddle, one ball, break the wall. Server-authoritative and deterministic
given `(config, seed, seats)`. The single seat submits `{"dir": "left"|"right"|""}`
each tick to move the paddle; missing action coasts (documented noop). The ball
bounces off the walls, paddle and bricks; each brick hit scores. Losing a life
happens when the ball drops below the floor. The game ends when all lives are
spent or every brick is cleared.
"""
import math
from typing import Any

from app.engine.base import BaseGame, IllegalMove


# Brick colors per row (top to bottom).
BRICK_COLORS = ["#f43f5e", "#f59e0b", "#3b82f6", "#22c55e"]


class Breakout(BaseGame):
    mode = "realtime"
    name = "breakout"
    CATALOG = {
        "title": "Breakout",
        "min_players": 1,
        "max_players": 1,
        "players_before_start": 1,
        "elo_ranked": False,
        "blurb": "Solo brick-busting. Two paddles, one goal: clear the wall.",
    }
    CONFIG_DEFAULTS = {
        "players": 1,
        "players_before_start": 1,
        "lives": 3,
        "cols": 14,
        "rows": 24,
        "brick_rows": 4,
        "paddle_w": 4.0,
        "paddle_speed": 1.6,
        "ball_speed": 1.15,
        "ball_r": 0.5,
    }

    def reset(self) -> None:
        self.cols = int(self.config["cols"])
        self.rows = int(self.config["rows"])
        self.brick_rows = int(self.config["brick_rows"])
        self.paddle_w = float(self.config["paddle_w"])
        self.paddle_speed = float(self.config["paddle_speed"])
        self.ball_speed = float(self.config["ball_speed"])
        self.ball_r = float(self.config["ball_r"])

        self.tick = 0
        self.lives = int(self.config["lives"])
        self.score = 0

        # paddle x is the left edge in cell units; paddle sits on the bottom row.
        self.paddle_x = self.cols / 2.0 - self.paddle_w / 2.0
        self.paddle_y = self.rows - 1.0  # top surface of the paddle

        self.bricks: set[tuple[int, int]] = {
            (r, c)
            for r in range(self.brick_rows)
            for c in range(self.cols)
        }

        self.ball: dict[str, float] = {}
        self._serve()
        self.last_move = None
        self._terminal = False
        self._winner: list[int] | None = None

    def _serve(self) -> None:
        """Place the ball on the paddle and launch it upward-ish after a tiny
        drop; serve angle is randomized via self.rng for determinism."""
        self.ball["x"] = self.paddle_x + self.paddle_w / 2.0
        self.ball["y"] = self.paddle_y - self.ball_r - 0.01
        ang = self.rng.uniform(-0.68, 0.68)  # radians from vertical
        dx = math.sin(ang) * self.ball_speed
        dy = -math.cos(ang) * self.ball_speed  # negative => upward into bricks
        # keep a minimum upward speed so the ball reliably clears the paddle.
        self.ball["dx"] = dx
        self.ball["dy"] = -self.ball_speed if abs(dy) < 0.15 * self.ball_speed else dy

    # ---- realtime ---------------------------------------------------------
    def step(self, moves: dict[int, Any]) -> None:
        mv = moves.get(0)
        self.last_move = None
        if mv is not None and isinstance(mv, dict):
            d = mv.get("dir", "")
            if d == "left":
                self.paddle_x -= self.paddle_speed
            elif d == "right":
                self.paddle_x += self.paddle_speed
        self.paddle_x = max(0.0, min(self.cols - self.paddle_w, self.paddle_x))

        # integrate ball
        self.ball["x"] += self.ball["dx"]
        self.ball["y"] += self.ball["dy"]

        # wall bounces (left/right/top)
        if self.ball["x"] - self.ball_r < 0:
            self.ball["x"] = self.ball_r
            self.ball["dx"] = abs(self.ball["dx"])
        elif self.ball["x"] + self.ball_r > self.cols:
            self.ball["x"] = self.cols - self.ball_r
            self.ball["dx"] = -abs(self.ball["dx"])
        if self.ball["y"] - self.ball_r < 0:
            self.ball["y"] = self.ball_r
            self.ball["dy"] = abs(self.ball["dy"])

        # brick collisions
        hit_index: tuple[int, int] | None = self._collide_bricks()

        # paddle collision
        if (self.ball["dy"] > 0
                and self.ball["y"] + self.ball_r >= self.paddle_y
                and self.ball["y"] - self.ball_r <= self.paddle_y + 1.0
                and self.paddle_x - self.ball_r <= self.ball["x"] <= self.paddle_x + self.paddle_w + self.ball_r):
            self._bounce_paddle()

        # lose a life when the ball fully drops below the floor
        if self.ball["y"] - self.ball_r > self.rows:
            self.lives -= 1
            self.last_move = {"event": "life_lost", "lives": self.lives, "score": self.score}
            if self.lives > 0:
                self._serve()
            else:
                self._terminal = True
                self._winner = []

        if hit_index is not None and hit_index not in self.bricks:
            pass  # already handled in _collide_bricks

        self.tick += 1
        if not self.bricks:
            self._terminal = True
            self._winner = [0]

    def _collide_bricks(self) -> tuple[int, int] | None:
        """Check the ball against all bricks (AABB test) and resolve the hit."""
        bx, by = self.ball["x"], self.ball["y"]
        r = self.ball_r
        for (r0, c) in sorted(self.bricks):
            cx, cy = c + 0.5, r0 + 0.5
            ox = r + 0.5 - abs(bx - cx)
            oy = r + 0.5 - abs(by - cy)
            if ox < 0 or oy < 0:
                continue
            # resolve on the axis of smallest penetration to avoid double flips
            if ox < oy:
                self.ball["dx"] = -self.ball["dx"] if bx < cx else abs(self.ball["dx"])
                self.ball["x"] = cx - (0.5 + r) if bx < cx else cx + (0.5 + r)
            else:
                self.ball["dy"] = -self.ball["dy"] if by < cy else abs(self.ball["dy"])
                self.ball["y"] = cy - (0.5 + r) if by < cy else cy + (0.5 + r)
            self.bricks.discard((r0, c))
            self.score += 1
            self.last_move = {"event": "brick", "row": r0, "col": c, "score": self.score}
            return (r0, c)
        return None

    def _bounce_paddle(self) -> None:
        # aim depends on where the ball strikes the paddle
        rel = (self.ball["x"] - self.paddle_x) / self.paddle_w
        rel = max(0.0, min(1.0, rel))
        ang = (rel - 0.5) * 1.2  # -0.6..0.6 rad from vertical
        dx = math.sin(ang) * self.ball_speed
        dy = -math.cos(ang) * self.ball_speed
        self.ball["dx"] = dx
        self.ball["dy"] = dy
        self.ball["y"] = self.paddle_y - self.ball_r - 0.001

    # ---- shared -----------------------------------------------------------
    def is_terminal(self) -> bool:
        return bool(self._terminal)

    def get_winner(self) -> list[int] | None:
        return self._winner

    def get_scores(self) -> dict:
        return {"score": self.score, "lives": self.lives}

    def get_legal_actions(self, seat: int) -> list[dict]:
        return [{"dir": "left"}, {"dir": "right"}, {"dir": ""}]

    def get_render_data(self) -> dict:
        return {
            "w": self.cols,
            "h": self.rows,
            "paddle": {"x": round(self.paddle_x, 3), "w": self.paddle_w},
            "ball": {
                "x": round(self.ball["x"], 3),
                "y": round(self.ball["y"], 3),
                "dx": round(self.ball["dx"], 3),
                "dy": round(self.ball["dy"], 3),
            },
            "bricks": [[r, c, BRICK_COLORS[r % len(BRICK_COLORS)]] for (r, c) in sorted(self.bricks)],
            "score": self.score,
            "lives": self.lives,
        }

    def observe(self, perspective: int | None = None) -> dict:
        return {
            "state": {
                "w": self.cols,
                "h": self.rows,
                "paddle": {"x": self.paddle_x, "w": self.paddle_w, "y": self.paddle_y},
                "ball": dict(self.ball),
                "ball_r": self.ball_r,
                "bricks": [[r, c] for (r, c) in sorted(self.bricks)],
                "brick_rows": self.brick_rows,
            },
            "legal_actions": [self.get_legal_actions(0) for _ in self.seats],
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": self.last_move,
            "time": None,
        }

    def summary(self) -> str:
        remaining = len(self.bricks)
        if self.is_terminal():
            if self._winner == [0]:
                return f"Breakout cleared all {self.cols * self.brick_rows} bricks (score {self.score})"
            return f"Breakout over — {self.lives} lives left, {self.score} pts"
        return f"Breakout {self.score} pts, {self.lives} lives, {remaining} bricks left"


CATALOG = {
    "game": "breakout",
    "mode": "realtime",
    "name": "Breakout",
    "players": {"min": 1, "max": 1},
    "players_before_start": 1,
    "elo_ranked": False,
    "blurb": "One paddle, one ball, break the wall.",
}
