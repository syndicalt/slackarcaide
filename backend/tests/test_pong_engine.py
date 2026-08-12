"""Pong engine tests: robustness, determinism, physics, and game flow.

Covers the failure modes found in adversarial review:
  * malformed/garbage client actions must never raise inside engine.step
    (a ValueError used to kill the match loop and strand the match);
  * vy is a clamped multiplier, so clients cannot teleport paddles;
  * continuous collision must not let fast diagonal balls tunnel through
    a paddle face or clip through its corner;
  * serve delay freezes the ball after a score; serve goes to the conceder;
  * same (config, seed, action sequence) => identical state (replay parity).
"""
import math

from app.engine.games.pong import BALL_R, H, PADDLE_H, PADDLE_W, W, Pong


def _engine(**config) -> Pong:
    return Pong(config=config, seed=7, seats=[{"seat": 0}, {"seat": 1}])


def _snapshot(e: Pong) -> dict:
    return {
        "ball": dict(e.ball),
        "paddles": dict(e.paddles),
        "scores": (e.point_left, e.point_right),
        "tick": e.tick,
    }


def test_garbage_actions_never_raise_and_never_move():
    e = _engine()
    junk = [
        {"vy": "not-a-number"},
        {"vy": float("nan")},
        {"vy": float("inf")},
        {"vy": None},
        {"vy": {"nested": 1}},
        {"action": "sideways"},
        {"action": 42},
        "a string, not a dict",
        1234,
        [("up",)],
    ]
    for action in junk:
        before = dict(e.paddles)
        e.step({0: action, 1: action})  # must not raise
        assert e.paddles == before, f"garbage action {action!r} moved a paddle"


def test_vy_is_clamped_to_paddle_speed():
    e = _engine()
    e._serve_timer = 0
    start = e.paddles[0]
    e.step({0: {"vy": 1_000_000_000}})
    moved = e.paddles[0] - start
    assert moved == float(e.config["paddle_speed"])  # not 1e9 * speed


def test_valid_actions_steer_paddles_and_coast_on_noop():
    e = _engine()
    e._serve_timer = 0
    start = e.paddles[0]
    e.step({0: {"action": "up"}})
    assert e.paddles[0] < start
    # no action next tick => coasts upward with last velocity (documented policy)
    mid = e.paddles[0]
    e.step({})
    assert e.paddles[0] < mid
    # explicit noop stops the coast
    e.step({0: {"action": "noop"}})
    stopped = e.paddles[0]
    e.step({})
    assert e.paddles[0] == stopped


def test_paddles_clamped_to_field():
    e = _engine()
    e._serve_timer = 0
    for _ in range(100):
        e.step({0: {"action": "up"}, 1: {"action": "down"}})
    assert e.paddles[0] == 0.0
    assert e.paddles[1] == H - PADDLE_H


def test_serve_delay_freezes_ball_then_releases():
    e = _engine(serve_delay_ticks=10)
    assert e._serve_timer == 10
    for _ in range(10):
        e.step({})
        assert e.ball["x"] == W / 2.0 and e.ball["y"] == H / 2.0
    assert e._serve_timer == 0
    e.step({})
    assert e.ball["x"] != W / 2.0  # ball is live again


def test_score_serves_toward_conceder_with_delay():
    e = _engine(win_points=99, serve_delay_ticks=5)
    e._serve_timer = 0
    # force a goal on the left side (seat 1 scores, seat 0 concedes)
    e.ball.update({"x": -19 - abs(e.ball["vx"]), "vx": -abs(e.ball["vx"])})
    e.step({})
    assert e.point_right == 1
    assert e._serve_timer == 5
    assert e.ball["x"] == W / 2.0
    assert e.ball["vx"] < 0  # served toward seat 0 (the conceder)
    assert e.last_move["event"] == "score" and e.last_move["seat"] == 1


def test_fast_diagonal_ball_does_not_tunnel_through_face():
    """The classic tunneling case: ball crosses the face plane inside the
    paddle's span but is out of vertical range by tick-end."""
    e = _engine()
    e._serve_timer = 0
    e.paddles[0] = 200.0  # paddle spans y 200..290
    # crosses the face plane (x=20) at y=208.75 (inside span) but ends the
    # tick at y=215 — a naive end-of-tick overlap test would miss nothing here,
    # but the sweep must place the ball exactly at the contact point.
    e.ball.update({"x": 50.0, "y": 190.0, "vx": -40.0, "vy": 25.0})
    e.step({})
    assert e.ball["vx"] > 0  # bounced, not through
    assert e.ball["x"] == PADDLE_W + BALL_R  # placed at the contact point


def _min_distance_to_paddle(e, seat):
    lx, rx = (0.0, PADDLE_W) if seat == 0 else (W - PADDLE_W, W)
    top, bot = e.paddles[seat], e.paddles[seat] + PADDLE_H
    nx = max(lx, min(e.ball["x"], rx))
    ny = max(top, min(e.ball["y"], bot))
    return math.hypot(e.ball["x"] - nx, e.ball["y"] - ny)


def test_past_face_plane_still_catches_edge_graze_right():
    """A fast ball can be horizontally past the leading face plane yet still
    carry a large vertical velocity into the paddle's edge. It must graze the
    edge (keep moving toward the wall, flip vertical) — never tunnel through.
    Regression for the removed `x >= left - r` early-out."""
    e = _engine()
    e._serve_timer = 0
    e.paddles[1] = (H - PADDLE_H) / 2.0
    # right paddle face at left - BALL_R = 780; ball at x=789.96 is already
    # past that plane, but vy=+58 drives it down into the top edge (top=205).
    e.ball.update({"x": 789.964, "y": 196.115, "vx": 15.399, "vy": 57.990})
    e.step({})
    # edge graze: keeps going right, vertical flips up; and stays solid
    assert e.ball["vx"] > 0
    assert e.ball["vy"] < 0
    assert _min_distance_to_paddle(e, 1) >= BALL_R - 1e-6


def test_past_face_plane_still_catches_edge_graze_left():
    """Mirror of the above: ball already past the left paddle's face plane
    (x < 20) but still descending into its top edge."""
    e = _engine()
    e._serve_timer = 0
    e.paddles[0] = (H - PADDLE_H) / 2.0
    e.ball.update({"x": 10.036, "y": 196.115, "vx": -15.399, "vy": 57.990})
    e.step({})
    assert e.ball["vx"] < 0   # edge graze keeps pushing toward the wall
    assert e.ball["vy"] < 0   # vertical flipped up
    assert _min_distance_to_paddle(e, 0) >= BALL_R - 1e-6


def test_corner_graze_hits_paddle_edge_not_tunnel():
    """Ball approaches just past the face span but clips the top edge."""
    e = _engine()
    e._serve_timer = 0
    e.paddles[0] = 300.0  # paddle top at y=300; inflated top edge at y=294
    # Threads the corner: crosses the face plane (x=20) at y=293.7 — just above
    # the inflated face span [294, 396] — then clips the top edge segment.
    e.ball.update({"x": 21.0, "y": 293.2, "vx": -2.0, "vy": 1.0})
    e.step({})
    # edge graze keeps horizontal direction, flips vertical
    assert e.ball["vx"] < 0
    assert e.ball["vy"] < 0


def test_ball_capped_at_max_speed():
    e = _engine(ball_speed=44.0, max_ball_speed=45.0, time_accel_rate=1.0, accel_interval=1)
    e._serve_timer = 0
    for _ in range(50):
        e.step({})
    speed = math.hypot(e.ball["vx"], e.ball["vy"])
    assert speed <= 45.0 + 1e-9


def test_determinism_same_seed_same_actions():
    def run():
        e = _engine(serve_delay_ticks=0)
        for t in range(600):
            moves = {}
            if t % 3 == 0:
                moves[0] = {"vy": 0.7}
            if t % 4 == 0:
                moves[1] = {"action": "up"}
            e.step(moves)
        return _snapshot(e)

    a, b = run(), run()
    assert a == b


def test_full_game_reaches_terminal_with_winner():
    """Two perfect trackers rally; with continuous acceleration the game must
    terminate at exactly win_points for one side."""
    e = _engine(win_points=3, serve_delay_ticks=0)

    def track(seat: int) -> dict:
        target = e.ball["y"]
        center = e.paddles[seat] + PADDLE_H / 2.0
        return {"vy": max(-1.0, min(1.0, (target - center) / 50.0))}

    for _ in range(200_000):
        if e.is_terminal():
            break
        e.step({0: track(0), 1: track(1)})
    assert e.is_terminal(), "perfect trackers never finished a game"
    assert max(e.point_left, e.point_right) == 3
    assert e.get_winner() in ([0], [1])
    # scores in observation agree with engine internals
    assert e.get_scores() == {"left": e.point_left, "right": e.point_right}
