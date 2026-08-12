"""Pong — 2-player realtime engine (spec §8.1).

Reference implementation for the realtime loop. Server-authoritative and
deterministic given seed. Actions per player are `{"action": "up"|"down"|"noop"}`
or `{"vy": float}` where vy is a multiplier in [-1, 1] of `paddle_speed`.
Anything else is ignored (documented noop); on a tick with no action a paddle
coasts with its last velocity (documented last-action policy).

Physics model follows Jake Gordon's javascript-pong (jakesgordon.com/writing/
javascript-pong/part4), adapted to our tick-based authoritative loop:
  * Continuous collision: the ball is swept along this tick's straight-line
    path and tested against the paddle's face segment AND its top/bottom edge
    segments (all inflated by the ball radius), so fast diagonal balls can
    neither tunnel through the face nor clip through a corner.
  * Face hits reflect the horizontal component, accelerate the ball, add a
    Kivy-style deflection "cut" proportional to the off-center contact point,
    and add Gordon-style spin from the paddle's own velocity.
  * After a score the ball freezes at center for `serve_delay_ticks` and is
    served toward the player who conceded the point (classic convention).
"""
import math
from typing import Any

from app.engine.base import BaseGame

# Game field in "units" (logical space the web UI scales to its canvas).
W, H = 800, 500
PADDLE_H = 90
PADDLE_W = 14
BALL_R = 6.0  # must stay in sync with get_render_data()["ball"]["r"]: every solid
              # collision (paddle face/edges, walls) is computed on this radius.
DT = 1.0  # arbitrary per-tick delta; tuned with speeds below

# Paddle rects in field space: seat 0 hugs x=0, seat 1 hugs x=W-PADDLE_W.
# Renderers must draw these exact rects for ball/paddle contact to line up.
_PADDLE_X = {0: 0.0, 1: W - PADDLE_W}


class Pong(BaseGame):
    mode = "realtime"
    name = "pong"
    CATALOG = {
        "title": "Pong",
        "min_players": 2,
        "max_players": 2,
        "players_before_start": 2,
        "elo_ranked": True,
        "blurb": "Two-player paddle tennis. First to 11.",
    }
    CONFIG_DEFAULTS = {
        "max_players": 2,
        "win_points": 11,
        "tick_rate": 30,
        # Classic pong curve: the ball starts slow (~1.8s to cross the field)
        # and accelerates over the rally (per hit + per second) and per point,
        # up to a hard cap so the game stays watchable.
        "ball_speed": 15.0,        # serve speed (slow start)
        "max_ball_speed": 60.0,    # velocity cap (~0.4s to cross)
        "ball_accel": 1.04,        # multiplier per paddle hit
        "speedup": 1.06,           # multiplier per point scored
        "time_accel_rate": 0.02,   # continuous +2%/s during play
        "accel_interval": 30,      # ticks (30 == ~1s at tick_rate 30)
        "paddle_speed": 20.0,
        "serve_delay_ticks": 30,   # ball frozen at center after a score (~1s)
        "paddle_spin": True,       # moving paddles add/remove vertical spin
        # Paddle deflection (Kivy style): how far off-center a hit cuts the
        # ball vertically. A dead-center hit bounces straight back; a hit near
        # the paddle edge darts up/down by up to this angle relative to the
        # (flipped) incoming horizontal component. Radians.
        "max_deflect_angle": math.pi / 3.0,
    }

    def reset(self) -> None:
        self.point_left = 0
        self.point_right = 0
        self.tick = 0
        paddle_y = (H - PADDLE_H) / 2.0
        self.paddles = {0: paddle_y, 1: paddle_y}  # top edge y per seat
        self.vys = {0: 0.0, 1: 0.0}
        self.ball = {"x": W / 2.0, "y": H / 2.0, "vx": 0.0, "vy": 0.0}
        self._current_speed = float(self.config["ball_speed"])
        self._serve_timer = 0
        self._serve(toward_seat=None)
        self.last_move = None

    def _serve(self, toward_seat: int | None) -> None:
        """Park the ball at center and arm the serve timer. When `toward_seat`
        is given (after a score), the ball is served toward that player's side
        so the conceder gets first touch; at match start the direction is
        random (seeded)."""
        if toward_seat is None:
            direction = -1.0 if self.rng.random() < 0.5 else 1.0
        else:
            direction = -1.0 if toward_seat == 0 else 1.0
        speed = self._current_speed
        self.ball["x"] = W / 2.0
        self.ball["y"] = H / 2.0
        self.ball["vx"] = speed * direction
        self.ball["vy"] = (self.rng.random() - 0.5) * speed * 0.5
        self._serve_timer = int(self.config["serve_delay_ticks"])

    # ---- action parsing -----------------------------------------------------
    def _parse_action(self, mv: Any) -> float | None:
        """Map a submitted action to a velocity multiplier in [-1, 1].

        Returns None for missing/malformed actions (documented coast noop).
        Never raises: client garbage must not be able to kill the match loop.
        """
        if not isinstance(mv, dict):
            return None
        if "vy" in mv:
            try:
                v = float(mv["vy"])
            except (TypeError, ValueError):
                return None
            if not math.isfinite(v):
                return None
            return max(-1.0, min(1.0, v))
        action = mv.get("action")
        if action == "up":
            return -1.0
        if action == "down":
            return 1.0
        if action == "noop":
            return 0.0
        return None

    # ---- realtime ---------------------------------------------------------
    def step(self, moves: dict[int, Any]) -> None:
        for seat in (0, 1):
            mult = self._parse_action(moves.get(seat))
            if mult is not None:
                self.vys[seat] = mult * float(self.config["paddle_speed"])

        # integrate paddles (allowed during serve delay so players can ready up)
        for seat in (0, 1):
            self.paddles[seat] += self.vys[seat] * DT
            self.paddles[seat] = max(0.0, min(H - PADDLE_H, self.paddles[seat]))

        if self._serve_timer > 0:
            self._serve_timer -= 1
            self.tick += 1
            return

        # ---- solid ball integration (continuous collision) ----
        prev_x, prev_y = self.ball["x"], self.ball["y"]
        end_x = prev_x + self.ball["vx"] * DT
        end_y = prev_y + self.ball["vy"] * DT

        hit = self._ball_intercept(prev_x, prev_y, end_x - prev_x, end_y - prev_y)
        if hit is not None:
            seat, contact, kind = hit
            if kind == "face":
                self._bounce_paddle_face(seat, contact[1])
            else:
                # edge graze: keep horizontal direction, flip vertical
                self.ball["vx"] *= float(self.config["ball_accel"])
                self.ball["vy"] = -self.ball["vy"] * float(self.config["ball_accel"])
                self._clamp_ball_speed()
            self.ball["x"], self.ball["y"] = contact
        else:
            # No paddle contact this tick: move along the straight path and
            # bounce off the solid top/bottom walls.
            self.ball["x"] = end_x
            self.ball["y"] = end_y
            if self.ball["y"] < 0:
                self.ball["y"] = -self.ball["y"]
                self.ball["vy"] = abs(self.ball["vy"])
            elif self.ball["y"] > H:
                self.ball["y"] = 2 * H - self.ball["y"]
                self.ball["vy"] = -abs(self.ball["vy"])

        # continuous time-based acceleration (not just on point/victory)
        interval = int(self.config["accel_interval"])
        if self.tick > 0 and self.tick % interval == 0:
            self._accelerate_time()

        # score / re-serve (ball fully past the goal line)
        if self.ball["x"] < -20:
            self._score(scorer=1, conceder=0)
        elif self.ball["x"] > W + 20:
            self._score(scorer=0, conceder=1)

        self.tick += 1

    def _score(self, scorer: int, conceder: int) -> None:
        if scorer == 0:
            self.point_left += 1
        else:
            self.point_right += 1
        self.last_move = {
            "event": "score",
            "seat": scorer,
            "scores": [self.point_left, self.point_right],
        }
        self._bump_speed()
        self._serve(toward_seat=conceder)

    # ---- collision (Gordon-style segment sweep) -----------------------------
    @staticmethod
    def _segment_intercept(
        x1: float, y1: float, x2: float, y2: float,
        x3: float, y3: float, x4: float, y4: float,
    ) -> tuple[float, float] | None:
        """Intersection point of segments (x1,y1)-(x2,y2) and (x3,y3)-(x4,y4)."""
        denom = ((y4 - y3) * (x2 - x1)) - ((x4 - x3) * (y2 - y1))
        if denom == 0:
            return None
        ua = (((x4 - x3) * (y1 - y3)) - ((y4 - y3) * (x1 - x3))) / denom
        if not (0 <= ua <= 1):
            return None
        ub = (((x2 - x1) * (y1 - y3)) - ((y2 - y1) * (x1 - x3))) / denom
        if not (0 <= ub <= 1):
            return None
        return (x1 + ua * (x2 - x1), y1 + ua * (y2 - y1))

    def _ball_intercept(
        self, x: float, y: float, nx: float, ny: float
    ) -> tuple[int, tuple[float, float], str] | None:
        """Sweep the ball along (nx, ny) against the paddle it approaches.

        Tests the radius-inflated face segment first, then the top/bottom
        edge segment (the "just grazed the corner" case most pong clones miss).
        Returns (seat, contact_point, "face"|"edge") or None.
        """
        if nx == 0:
            return None
        seat = 0 if nx < 0 else 1
        r = BALL_R
        left, right = _PADDLE_X[seat], _PADDLE_X[seat] + PADDLE_W
        top, bottom = self.paddles[seat], self.paddles[seat] + PADDLE_H

        # No "already past the face plane" early-out on purpose: a fast ball
        # carries a large cross speed, so it can be horizontally past the
        # leading face and still clip the paddle's top/bottom edge while it
        # keeps descending/rising into the paddle's span. The segment sweeps
        # below self-guard (they return None when there is no crossing), so we
        # always test the face AND the edge a ball is currently heading toward.

        # face segment (right edge of left paddle / left edge of right paddle)
        fx = (right + r) if nx < 0 else (left - r)
        pt = self._segment_intercept(x, y, x + nx, y + ny, fx, top - r, fx, bottom + r)
        if pt is not None:
            return (seat, pt, "face")

        # edge segment: a descending ball clips the paddle's top edge, a
        # rising ball its bottom edge (corner grazes the face sweep missed)
        if ny > 0:
            ey = top - r
        elif ny < 0:
            ey = bottom + r
        else:
            return None
        pt = self._segment_intercept(
            x, y, x + nx, y + ny, left - r, ey, right + r, ey
        )
        if pt is not None:
            return (seat, pt, "edge")
        return None

    def _bounce_paddle_face(self, seat: int, y_contact: float) -> None:
        # Kivy-style paddle deflection (kivy.org/doc/stable/tutorials/pong.html,
        # PongPaddle.bounce_ball): flip the horizontal component and keep the
        # vertical, then ADD a vertical cut proportional to how far off-center
        # the ball struck the paddle. A dead-center hit bounces straight back;
        # an edge hit darts up or down (the classic "cut" shot).
        #
        # `y_contact` is the Y where the ball actually touched the face this
        # tick (from the continuous sweep), so the cut is computed at the true
        # impact point.
        rel = (y_contact - (self.paddles[seat] + PADDLE_H / 2.0)) / (PADDLE_H / 2.0)
        accel = float(self.config["ball_accel"])
        vx = -self.ball["vx"] * accel                     # flip horizontal, grow
        vy = self.ball["vy"] * accel                      # keep vertical, grow
        cut = rel * abs(vx) * math.tan(float(self.config["max_deflect_angle"]))
        vy += cut

        # Gordon-style spin: a paddle moving with the ball's vertical direction
        # amplifies it (1.5x), moving against it damps it (0.5x).
        if self.config.get("paddle_spin"):
            pv = self.vys[seat]
            if pv < 0:
                vy *= 0.5 if vy < 0 else 1.5
            elif pv > 0:
                vy *= 1.5 if vy < 0 else 0.5

        self.ball["vx"], self.ball["vy"] = vx, vy
        self._clamp_ball_speed()

    def _bump_speed(self) -> None:
        """Per-point speed-up: raise the persistent serve speed, capped."""
        self._current_speed = min(
            self._current_speed * float(self.config["speedup"]),
            float(self.config["max_ball_speed"]),
        )

    def _clamp_ball_speed(self) -> None:
        """Rescale the ball's velocity toward max_ball_speed once it crosses it."""
        mx = float(self.config["max_ball_speed"])
        cur = math.hypot(self.ball["vx"], self.ball["vy"])
        if cur > mx and cur > 0:
            k = mx / cur
            self.ball["vx"] *= k
            self.ball["vy"] *= k

    def _accelerate_time(self) -> None:
        """Continuous in-rally acceleration so a long rally visibly speeds up."""
        f = 1.0 + float(self.config["time_accel_rate"])
        self.ball["vx"] *= f
        self.ball["vy"] *= f
        self._clamp_ball_speed()

    # ---- shared -----------------------------------------------------------
    def is_terminal(self) -> bool:
        return max(self.point_left, self.point_right) >= int(self.config["win_points"])

    def get_winner(self) -> list[int] | None:
        if not self.is_terminal():
            return None
        return [0] if self.point_left > self.point_right else [1]

    def get_scores(self) -> dict:
        return {"left": self.point_left, "right": self.point_right}

    def get_legal_actions(self, seat: int) -> list[dict]:
        return [
            {"action": "up"},
            {"action": "down"},
            {"action": "noop"},
            {"vy": 0.0},
        ]

    def get_render_data(self) -> dict:
        return {
            "w": W,
            "h": H,
            "paddle_w": PADDLE_W,
            "paddle_h": PADDLE_H,
            # top-edge y per paddle; paddles sit at x=0 and x=w-paddle_w
            "paddles": [self.paddles[0], self.paddles[1]],
            "ball": {"x": self.ball["x"], "y": self.ball["y"], "r": BALL_R},
            "scores": [self.point_left, self.point_right],
            "serve_in": self._serve_timer,
        }

    def summary(self) -> str:
        win = self.config["win_points"]
        base = f"Pong {self.point_left}-{self.point_right} (first to {win})"
        if self.is_terminal():
            w = self.get_winner()
            return f"Pong over {self.point_left}-{self.point_right} — player {w[0] if w else '?'} wins"
        return base

    def observe(self, perspective: int | None = None) -> dict:
        return {
            "state": {
                "paddles": [self.paddles[0], self.paddles[1]],
                "velocities": [self.vys[0], self.vys[1]],
                "ball": {"x": self.ball["x"], "y": self.ball["y"],
                         "vx": self.ball["vx"], "vy": self.ball["vy"]},
                "paddle_h": PADDLE_H,
                "paddle_w": PADDLE_W,
                "w": W,
                "h": H,
                "serve_in": self._serve_timer,
            },
            "legal_actions": [[{"action": "up"}, {"action": "down"}, {"action": "noop"}] for _ in self.seats],
            "scores": {"left": self.point_left, "right": self.point_right},
            "summary": self.summary(),
            "last_move": self.last_move,
            "time": None,
        }
