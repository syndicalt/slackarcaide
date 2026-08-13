"""Production-boundary, configuration, clock, and terminal-state invariants."""

from __future__ import annotations

import math

import chess
import pytest
from pydantic import ValidationError

from app.engine import base
from app.engine.base import IllegalMove
from app.engine.games.battleship import Battleship
from app.engine.games.bomberman import Bomberman
from app.engine.games.checkers import Checkers
from app.engine.games.chess import Chess
from app.engine.games.chess960 import Chess960
from app.engine.games.connect_four import ConnectFour
from app.engine.games.go import Go
from app.engine.games.pong import BALL_R, H, Pong, W
from app.engine.games.reversi import Reversi
from app.engine.games.tetris import Tetris
from app.engine.games.tron import Tron
from app.engine.games.ultimate_ttt import UltimateTicTacToe
from app.engine.registry import GAMES_CATALOG, REGISTRY, normalize_game_config

SEATS = [
    {"seat": 0, "agent_id": "white"},
    {"seat": 1, "agent_id": "black"},
]


def _chess(**config: object) -> Chess:
    return Chess(config=config, seed=1, seats=list(SEATS))


def _pong(**config: object) -> Pong:
    return Pong(config=config, seed=1, seats=list(SEATS))


def test_production_registry_is_an_explicit_live_game_allowlist() -> None:
    expected = {
        "chess",
        "chess960",
        "connect_four",
        "reversi",
        "checkers",
        "go",
        "pong",
        "tron",
        "ultimate_ttt",
        "battleship",
        "bomberman",
        "tetris",
        "last_server",
    }
    assert set(REGISTRY) == expected
    assert {game["game"] for game in GAMES_CATALOG} == expected
    last_server = next(game for game in GAMES_CATALOG if game["game"] == "last_server")
    assert last_server["players"] == {"min": 5, "max": 7}
    assert last_server["players_before_start"] == 6
    assert last_server["elo_ranked"] is False
    assert all(
        game["players"] == {"min": 2, "max": 2} and game["elo_ranked"] is True
        for game in GAMES_CATALOG
        if game["game"] != "last_server"
    )


def test_registry_normalizes_trusted_config_before_match_persistence() -> None:
    config = normalize_game_config("pong", {"win_points": 7, "ranked": False})
    assert config["win_points"] == 7
    assert config["tick_rate"] == 30
    assert config["ranked"] is False
    with pytest.raises(ValidationError):
        normalize_game_config("pong", {"accel_interval": 0})
    with pytest.raises(KeyError):
        normalize_game_config("disabled-game", {})


@pytest.mark.parametrize(
    "engine",
    [
        Chess,
        Chess960,
        ConnectFour,
        Reversi,
        Checkers,
        Go,
        Pong,
        Tron,
        UltimateTicTacToe,
        Battleship,
        Bomberman,
        Tetris,
    ],
)
@pytest.mark.parametrize(
    ("seed", "seats"),
    [
        (-1, SEATS),
        (True, SEATS),
        ("1", SEATS),
        (2**63, SEATS),
        (1, SEATS[:1]),
        (1, [{"seat": 1}, {"seat": 0}]),
    ],
)
def test_live_engines_reject_invalid_seed_and_seat_topology(
    engine: type[base.BaseGame],
    seed: object,
    seats: list[dict],
) -> None:
    with pytest.raises(ValueError):
        engine(config={}, seed=seed, seats=seats)


@pytest.mark.parametrize(
    "config",
    [
        {"win_points": 0},
        {"win_points": -1},
        {"win_points": 101},
        {"tick_rate": 0},
        {"tick_rate": 241},
        {"accel_interval": 0},
        {"accel_interval": -1},
        {"ball_speed": 0.0},
        {"ball_speed": math.inf},
        {"max_ball_speed": math.nan},
        {"ball_speed": 61.0, "max_ball_speed": 60.0},
        {"ball_accel": 0.99},
        {"speedup": 0.5},
        {"time_accel_rate": -0.01},
        {"serve_delay_ticks": -1},
        {"max_deflect_angle": math.pi / 2},
        {"tick_rate": 240, "max_duration_seconds": 1_000},
        {"max_duration_seconds": 59},
        {"players_required": 1},
        {"max_players": 3},
        {"ranked": 0},
        {"win_points": "11"},
        {"invented_rule": True},
    ],
)
def test_pong_rejects_unsafe_or_unknown_admin_config(config: dict) -> None:
    with pytest.raises(ValidationError):
        Pong(config=config, seed=1, seats=list(SEATS))


def test_pong_accepts_safe_boundary_values() -> None:
    engine = _pong(
        win_points=100,
        tick_rate=240,
        max_duration_seconds=400,
        accel_interval=1,
        ball_speed=200.0,
        max_ball_speed=240.0,
        serve_delay_ticks=0,
        max_deflect_angle=0.0,
    )
    assert engine.config["win_points"] == 100
    assert engine.config["tick_rate"] == 240


def test_pong_duration_limit_adjudicates_an_endless_rally_as_a_draw() -> None:
    engine = _pong(tick_rate=10, max_duration_seconds=60)
    engine.tick = 599
    engine._serve_timer = 1

    engine.step({})

    assert engine.is_terminal()
    assert engine.get_winner() is None
    assert engine.ball["vx"] == engine.ball["vy"] == 0.0
    assert "draw" in engine.summary()


def test_pong_terminal_score_is_atomic_and_state_cannot_advance_afterward() -> None:
    engine = _pong(win_points=1, serve_delay_ticks=0)
    engine.paddles[1] = 0.0
    engine.ball.update({"x": W + 21.0, "y": H / 2, "vx": 1.0, "vy": 0.0})

    engine.step({})

    assert engine.is_terminal()
    assert engine.get_winner() == [0]
    assert engine.get_scores() == {"left": 1, "right": 0}
    assert engine.ball["vx"] == engine.ball["vy"] == 0.0
    assert engine._serve_timer == 0
    terminal_snapshot = (engine.tick, dict(engine.ball), dict(engine.paddles))

    engine.step({0: {"action": "up"}})
    assert (engine.tick, engine.ball, engine.paddles) == terminal_snapshot


def test_pong_wall_collision_respects_ball_radius() -> None:
    engine = _pong(serve_delay_ticks=0)
    engine.ball.update({"x": W / 2, "y": BALL_R + 1, "vx": 1.0, "vy": -20.0})
    engine.step({})
    assert engine.ball["y"] >= BALL_R
    assert engine.ball["vy"] > 0


def test_pong_reset_replays_seeded_initial_state() -> None:
    engine = _pong()
    initial_ball = dict(engine.ball)
    for _ in range(100):
        engine.step({0: {"action": "up"}})
    engine.reset()
    assert engine.ball == initial_ball
    assert engine.tick == 0
    assert not engine.is_terminal()


@pytest.mark.parametrize(
    "config",
    [
        {"time_control": {"base_sec": 0, "increment_sec": 0, "enabled": True}},
        {"time_control": {"base_sec": 60, "increment_sec": -1, "enabled": True}},
        {"time_control": {"base_sec": 86_401, "increment_sec": 0, "enabled": True}},
        {"time_control": {"base_sec": 60, "increment_sec": 3_601, "enabled": True}},
        {"time_control": {"base_sec": "60", "increment_sec": 0, "enabled": True}},
        {"time_control": {"base_sec": 60, "increment_sec": 0, "enabled": 1}},
        {"players_required": 1},
        {"ranked": 0},
        {"start_fen": "x" * 129},
        {"unknown_variant": "atomic"},
    ],
)
def test_chess_rejects_unsafe_or_unknown_admin_config(config: dict) -> None:
    with pytest.raises(ValidationError):
        Chess(config=config, seed=1, seats=list(SEATS))


def test_partial_chess_time_control_receives_bounded_defaults() -> None:
    engine = _chess(time_control={"base_sec": 30})
    assert engine.config["time_control"] == {
        "base_sec": 30,
        "increment_sec": 5,
        "enabled": True,
    }


def test_fischer_clock_runs_only_active_seat_and_accumulates_increment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 100.0
    monkeypatch.setattr(base.time, "monotonic", lambda: now)
    engine = _chess(time_control={"base_sec": 10, "increment_sec": 2, "enabled": True})

    now = 103.0
    assert engine.clock_ms(0) == 7_000
    assert engine.clock_ms(1) == 10_000

    engine.apply_action({"from": "e2", "to": "e4"})
    assert engine.clock_ms(0) == 9_000  # 10s - 3s + 2s increment
    assert engine.clock_ms(1) == 10_000

    now = 107.0
    assert engine.clock_ms(0) == 9_000
    assert engine.clock_ms(1) == 6_000
    clock = engine.observe()["time"]
    assert clock == {
        "remaining_ms": {"white": 9_000, "black": 6_000},
        "increment_ms": 2_000,
        "active_seat": 1,
    }


def test_clock_timeout_requires_flag_fall_and_freezes_terminal_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_000.0
    monkeypatch.setattr(base.time, "monotonic", lambda: now)
    engine = _chess(time_control={"base_sec": 5, "increment_sec": 0, "enabled": True})

    now = 1_004.0
    with pytest.raises(RuntimeError, match="still has"):
        engine.timeout_loss(0)

    now = 1_005.1
    engine.timeout_loss(0)
    assert engine.is_terminal()
    assert engine.get_winner() == [1]
    assert engine.move_count == 0
    assert engine.clock_ms(0) == 0
    assert engine.clock_ms(1) == 5_000
    assert engine.clock_state()["active_seat"] is None

    now = 2_000.0
    assert engine.clock_ms(1) == 5_000


def test_chess_rejects_move_after_flag_fall(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 200.0
    monkeypatch.setattr(base.time, "monotonic", lambda: now)
    engine = _chess(time_control={"base_sec": 1, "increment_sec": 0, "enabled": True})
    now = 201.1
    with pytest.raises(IllegalMove) as exc:
        engine.apply_action({"from": "e2", "to": "e4"})
    assert exc.value.code == "clock_expired"
    assert engine.board.piece_at(12) is not None  # e2 pawn did not move


def test_chess_reset_restores_position_and_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 300.0
    monkeypatch.setattr(base.time, "monotonic", lambda: now)
    engine = _chess(time_control={"base_sec": 10, "increment_sec": 1, "enabled": True})
    now = 303.0
    engine.apply_action({"from": "e2", "to": "e4"})
    now = 305.0
    engine.reset()
    assert engine.board.fen() == chess.Board().fen()
    assert engine.move_count == 0
    assert engine.clock_ms(0) == 10_000
    assert engine.clock_ms(1) == 10_000
    assert engine.clock_state()["active_seat"] == 0


def test_disabled_clock_is_absent_from_chess_observation() -> None:
    engine = _chess(time_control={"base_sec": 60, "increment_sec": 0, "enabled": False})
    assert engine.clock_ms(0) is None
    assert engine.clock_state() is None
    assert engine.observe()["time"] is None


def test_custom_black_to_move_position_starts_only_black_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 50.0
    monkeypatch.setattr(base.time, "monotonic", lambda: now)
    engine = _chess(start_fen="8/8/8/8/8/4k3/8/4K3 b - - 0 1")
    now = 51.0
    assert engine.clock_ms(0) == 600_000
    assert engine.clock_ms(1) == 599_000
