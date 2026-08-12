"""Asteroids — single-player realtime engine.

Server-authoritative and deterministic given `(config, seed, seats)`. The lone
player steers a ship, fires bullets at drifting asteroids, and survives until
every rock is cleared (win) or all lives are spent (loss). Asteroids split into
two smaller chunks when shot; the ship wraps at the screen edges along with
bullets and rocks.

Actions per tick (structured dict of booleans) are applied before physics:
    {"accel": bool, "left": bool, "right": bool, "fire": bool}
A missing or non-dict action is a documented noop.
"""
import math
from typing import Any

from app.engine.base import BaseGame, IllegalMove

TURN = 0.06          # radians per tick
THRUST = 0.22        # velocity added per tick while accelerating
DRAG = 0.985         # per-tick velocity damping
MAX_SPEED = 9.0
BULLET_SPEED = 10.0
MAX_BULLETS = 5
BULLET_LIFE = 60     # ticks
BULLET_COOLDOWN = 8  # ticks between shots
SHIP_R = 12.0        # collision radius
INVULN_TICKS = 90    # respawn shield

ASTEROID_R = 32.0    # largest spawn radius
ASTEROID_SPEED = 1.6
ASTEROID_N = 4       # asteroids at start


class Asteroids(BaseGame):
    mode = "realtime"
    name = "asteroids"
    CATALOG = {
        "title": "Asteroids",
        "min_players": 1,
        "max_players": 1,
        "players_before_start": 1,
        "elo_ranked": False,
        "blurb": "Solo shooter. Blast rocks until the field is clear.",
    }
    CONFIG_DEFAULTS = {
        "players": 1,
        "players_before_start": 1,
        "lives": 3,
        "w": 600,
        "h": 450,
    }

    def reset(self) -> None:
        self.tick = 0
        self.w = int(self.config["w"])
        self.h = int(self.config["h"])
        self.lives = int(self.config["lives"])
        self.score = 0
        self.angle = -math.pi / 2.0  # pointing up
        self.ship = {"x": self.w / 2.0, "y": self.h / 2.0, "vx": 0.0, "vy": 0.0}
        self.invuln_timer = 0
        self.fire_cooldown = 0
        self.ship_alive = True
        self.bullets: list[dict] = []
        self.asteroids: list[dict] = []
        self.last_move = None
        for _ in range(ASTEROID_N):
            self._spawn_asteroid()

    # ---- helpers ----------------------------------------------------------
    def _center_dist(self, x: float, y: float) -> float:
        return math.hypot(x - self.ship["x"], y - self.ship["y"])

    def _spawn_asteroid(self) -> None:
        r = ASTEROID_R
        # keep the spawn clear of the starting ship position
        for _ in range(120):
            x = self.rng.uniform(0, self.w)
            y = self.rng.uniform(0, self.h)
            if self._center_dist(x, y) > r + SHIP_R + 60:
                break
        else:
            x, y = self.w / 2.0, self.h / 2.0
        speed = self.rng.uniform(0.7, 1.3) * ASTEROID_SPEED
        a = self.rng.uniform(0, 2 * math.pi)
        self.asteroids.append({
            "x": x, "y": y,
            "dx": math.cos(a) * speed, "dy": math.sin(a) * speed,
            "r": r,
        })

    def _wrap(self, d: dict) -> None:
        if d["x"] < -d.get("r", 0) - 10:
            d["x"] += self.w + 20
        elif d["x"] > self.w + d.get("r", 0) + 10:
            d["x"] -= self.w + 20
        if d["y"] < -d.get("r", 0) - 10:
            d["y"] += self.h + 20
        elif d["y"] > self.h + d.get("r", 0) + 10:
            d["y"] -= self.h + 20

    def _split_asteroid(self, idx: int) -> None:
        ast = self.asteroids[idx]
        r = ast["r"]
        # score by size: bigger rocks are worth fewer, small ones the most
        self.score += 100 if r <= 12 else (50 if r <= 24 else 20)
        del self.asteroids[idx]
        if r <= 12:
            return  # smallest rock: destroyed outright
        child_r = r / 2.0
        speed = math.hypot(ast["dx"], ast["dy"]) * 1.25
        for _ in range(2):
            a = self.rng.uniform(0, 2 * math.pi)
            self.asteroids.append({
                "x": ast["x"], "y": ast["y"],
                "dx": math.cos(a) * speed, "dy": math.sin(a) * speed,
                "r": child_r,
            })

    def _destroy_ship(self) -> None:
        self.lives -= 1
        self.last_move = {"event": "ship_lost", "lives": max(0, self.lives)}
        if self.lives > 0:
            self.ship = {"x": self.w / 2.0, "y": self.h / 2.0, "vx": 0.0, "vy": 0.0}
            self.angle = -math.pi / 2.0
            self.invuln_timer = INVULN_TICKS
        else:
            self.ship_alive = False

    # ---- realtime ---------------------------------------------------------
    def step(self, moves: dict[int, Any]) -> None:
        mv = moves.get(0)
        accel = left = right = fire = False
        if isinstance(mv, dict):
            accel = bool(mv.get("accel"))
            left = bool(mv.get("left"))
            right = bool(mv.get("right"))
            fire = bool(mv.get("fire"))

        # ship controls (before physics)
        if self.ship_alive:
            if left:
                self.angle -= TURN
            if right:
                self.angle += TURN
            if accel:
                self.ship["vx"] += math.cos(self.angle) * THRUST
                self.ship["vy"] += math.sin(self.angle) * THRUST

            self.ship["vx"] *= DRAG
            self.ship["vy"] *= DRAG
            sp = math.hypot(self.ship["vx"], self.ship["vy"])
            if sp > MAX_SPEED:
                self.ship["vx"] *= MAX_SPEED / sp
                self.ship["vy"] *= MAX_SPEED / sp

            # fire
            if self.fire_cooldown > 0:
                self.fire_cooldown -= 1
            if fire and len(self.bullets) < MAX_BULLETS and self.fire_cooldown == 0:
                tip_x = self.ship["x"] + math.cos(self.angle) * (SHIP_R + 4)
                tip_y = self.ship["y"] + math.sin(self.angle) * (SHIP_R + 4)
                self.bullets.append({
                    "x": tip_x, "y": tip_y,
                    "dx": self.ship["vx"] + math.cos(self.angle) * BULLET_SPEED,
                    "dy": self.ship["vy"] + math.sin(self.angle) * BULLET_SPEED,
                    "life": BULLET_LIFE,
                })
                self.fire_cooldown = BULLET_COOLDOWN
                self.last_move = {"event": "fire"}

            if self.invuln_timer > 0:
                self.invuln_timer -= 1
            self.ship["x"] += self.ship["vx"]
            self.ship["y"] += self.ship["vy"]
            self._wrap(self.ship)

        # bullets
        for b in self.bullets:
            b["x"] += b["dx"]
            b["y"] += b["dy"]
            b["life"] -= 1
        self.bullets = [b for b in self.bullets if b["life"] > 0]
        for b in self.bullets:
            self._wrap(b)

        # asteroids
        for a in self.asteroids:
            a["x"] += a["dx"]
            a["y"] += a["dy"]
            self._wrap(a)

        # asteroid split on bullet hit
        hit = True
        while hit and self.bullets:
            hit = False
            for bi, b in enumerate(self.bullets):
                for ai, a in enumerate(self.asteroids):
                    if math.hypot(b["x"] - a["x"], b["y"] - a["y"]) <= a["r"] + 3:
                        del self.bullets[bi]
                        self._split_asteroid(ai)
                        self.last_move = {"event": "hit", "score": self.score}
                        hit = True
                        break
                if hit:
                    break

        # ship vs asteroids
        if self.ship_alive and self.invuln_timer <= 0:
            for a in self.asteroids:
                if math.hypot(self.ship["x"] - a["x"], self.ship["y"] - a["y"]) <= a["r"] + SHIP_R:
                    self._destroy_ship()
                    break

        self.tick += 1

    # ---- shared -----------------------------------------------------------
    def is_terminal(self) -> bool:
        return self.lives <= 0 or not self.asteroids

    def get_winner(self) -> list[int] | None:
        if not self.is_terminal():
            return None
        return [0] if self.lives > 0 else []

    def get_scores(self) -> dict:
        return {"0": self.score}

    def get_legal_actions(self, seat: int) -> list[dict]:
        return [
            {"accel": False, "left": False, "right": False, "fire": False},
            {"accel": True, "left": False, "right": False, "fire": False},
            {"accel": False, "left": True, "right": False, "fire": False},
            {"accel": False, "left": False, "right": True, "fire": False},
            {"accel": False, "left": False, "right": False, "fire": True},
        ]

    def get_render_data(self) -> dict:
        return {
            "w": self.w,
            "h": self.h,
            "ship": {
                "x": self.ship["x"],
                "y": self.ship["y"],
                "angle": self.angle,
                "invuln": self.invuln_timer > 0,
            },
            "bullets": [{"x": b["x"], "y": b["y"]} for b in self.bullets],
            "asteroids": [
                {"x": a["x"], "y": a["y"], "r": a["r"], "dx": a["dx"], "dy": a["dy"]}
                for a in self.asteroids
            ],
            "score": self.score,
            "lives": self.lives,
        }

    def summary(self) -> str:
        if self.is_terminal():
            return ("Asteroids cleared!" if self.lives > 0 else
                    f"Game over — score {self.score}")
        return (f"Asteroids — rocks left {len(self.asteroids)}, "
                f"lives {self.lives}, score {self.score}")

    def observe(self, perspective: int | None = None) -> dict:
        return {
            "state": {
                "ship": self.get_render_data()["ship"],
                "bullets": [{"x": b["x"], "y": b["y"], "vx": b["dx"], "vy": b["dy"]}
                            for b in self.bullets],
                "asteroids": [
                    {"x": a["x"], "y": a["y"], "r": a["r"], "dx": a["dx"], "dy": a["dy"]}
                    for a in self.asteroids
                ],
                "w": self.w,
                "h": self.h,
            },
            "legal_actions": self.get_legal_actions(0),
            "scores": {"0": self.score},
            "summary": self.summary(),
            "last_move": self.last_move,
            "time": None,
        }


CATALOG = {
    "game": "asteroids",
    "mode": "realtime",
    "name": "Asteroids",
    "players": {"min": 1, "max": 1},
    "players_before_start": 1,
    "elo_ranked": False,
    "blurb": "Blast rocks, dodge debris.",
}
