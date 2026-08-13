"""Adversarial contract tests for deterministic Light Cycles."""

from __future__ import annotations

import copy
import math
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.engine.games.tron import MAX_DIMENSION, MIN_DIMENSION, Tron


def _engine(engine_seed: int = 17, **config: Any) -> Tron:
    return Tron(config=config, seed=engine_seed, seats=[{"seat": 0}, {"seat": 1}])


def _put(
    engine: Tron,
    *,
    heads: list[tuple[int, int]],
    directions: list[int],
    trails: list[list[tuple[int, int]]] | None = None,
) -> None:
    engine.heads = heads.copy()
    engine.directions = directions.copy()
    engine.trails = copy.deepcopy(trails or [[heads[0]], [heads[1]]])
    engine._occupied = {cell for trail in engine.trails for cell in trail}


def test_defaults_have_symmetric_fair_start_and_bounded_state() -> None:
    engine = _engine()
    width = engine.config["width"]
    height = engine.config["height"]

    assert engine.heads[0][0] == width - 1 - engine.heads[1][0]
    assert engine.heads[0][1] == engine.heads[1][1] == height // 2
    assert engine.directions == [1, 3]
    assert engine.trails == [[engine.heads[0]], [engine.heads[1]]]
    assert MIN_DIMENSION <= width <= MAX_DIMENSION
    assert MIN_DIMENSION <= height <= MAX_DIMENSION


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({"width": MIN_DIMENSION - 1}, "greater than or equal"),
        ({"width": MAX_DIMENSION + 1}, "less than or equal"),
        ({"height": MIN_DIMENSION - 1}, "greater than or equal"),
        ({"height": MAX_DIMENSION + 1}, "less than or equal"),
        ({"tick_rate": 1}, "greater than or equal"),
        ({"tick_rate": 61}, "less than or equal"),
        ({"max_ticks": 0}, "greater than or equal"),
        ({"max_ticks": 10_001}, "less than or equal"),
        ({"width": True}, "valid integer"),
        ({"tick_rate": 10.0}, "valid integer"),
        ({"seed": math.inf}, "valid integer"),
        ({"invented_rule": 1}, "Extra inputs are not permitted"),
    ],
)
def test_config_is_strict_and_resource_bounded(config: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _engine(**config)


def test_base_contract_rejects_bad_seed_and_seat_shapes() -> None:
    with pytest.raises(ValueError, match="seed"):
        Tron(config={}, seed=-1, seats=[{"seat": 0}, {"seat": 1}])
    with pytest.raises(ValueError, match="expected 2 seats"):
        Tron(config={}, seed=1, seats=[{"seat": 0}])
    with pytest.raises(ValueError, match="ordered"):
        Tron(config={}, seed=1, seats=[{"seat": 1}, {"seat": 0}])


def test_relative_turns_are_applied_simultaneously() -> None:
    engine = _engine()
    left_start, right_start = engine.heads

    engine.step({0: {"turn": "left"}, 1: {"turn": "right"}})

    assert engine.directions == [0, 0]
    assert engine.heads == [
        (left_start[0], left_start[1] - 1),
        (right_start[0], right_start[1] - 1),
    ]
    assert engine.tick == engine.move_count == 1


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        True,
        7,
        math.nan,
        math.inf,
        "left",
        ["left"],
        {"turn": None},
        {"turn": math.nan},
        {"turn": ["left"]},
        {"turn": "up"},
        {"turn": "left", "extra": True},
        {},
    ],
)
def test_missing_and_malformed_actions_are_documented_straight_noops(garbage: Any) -> None:
    engine = _engine()
    starts = engine.heads.copy()

    engine.step({0: garbage})

    assert engine.last_move is not None
    assert engine.last_move["turns"] == ["straight", "straight"]
    assert engine.heads == [
        (starts[0][0] + 1, starts[0][1]),
        (starts[1][0] - 1, starts[1][1]),
    ]


def test_malformed_moves_envelope_is_treated_as_both_missing() -> None:
    engine = _engine()
    starts = engine.heads.copy()

    engine.step(cast(dict[int, Any], None))

    assert engine.heads == [(starts[0][0] + 1, starts[0][1]), (starts[1][0] - 1, starts[1][1])]


def test_lone_wall_crash_awards_survivor() -> None:
    engine = _engine(width=9, height=9)
    _put(engine, heads=[(0, 2), (6, 6)], directions=[3, 1])

    engine.step({})

    assert engine.is_terminal()
    assert engine.get_winner() == [1]
    assert engine.alive == [False, True]
    assert engine.heads == [(0, 2), (7, 6)]
    assert engine.crashes == [{"seat": 0, "at": [-1, 2], "reasons": ["wall"]}]


@pytest.mark.parametrize("opponent_trail", [False, True])
def test_collision_with_either_trail_is_terminal(opponent_trail: bool) -> None:
    engine = _engine(width=9, height=9)
    trails = [[(1, 2), (2, 2)], [(7, 7)]]
    if opponent_trail:
        trails = [[(2, 2)], [(1, 2), (7, 7)]]
    _put(engine, heads=[(2, 2), (7, 7)], directions=[3, 0], trails=trails)

    engine.step({})

    assert engine.get_winner() == [1]
    assert engine.crashes[0]["reasons"] == ["trail"]


def test_same_cell_head_on_is_a_simultaneous_draw() -> None:
    engine = _engine(width=9, height=9)
    _put(engine, heads=[(3, 4), (5, 4)], directions=[1, 3])

    engine.step({})

    assert engine.is_terminal()
    assert engine.get_winner() is None
    assert engine.alive == [False, False]
    assert [crash["reasons"] for crash in engine.crashes] == [["head_on"], ["head_on"]]
    assert (4, 4) not in engine._occupied


def test_head_swap_crossing_is_a_simultaneous_draw() -> None:
    engine = _engine(width=9, height=9)
    _put(engine, heads=[(3, 4), (4, 4)], directions=[1, 3])

    engine.step({})

    assert engine.is_terminal()
    assert engine.get_winner() is None
    for crash in engine.crashes:
        assert crash["reasons"] == ["trail", "crossing"]


def test_unrelated_simultaneous_crashes_are_also_a_draw() -> None:
    engine = _engine(width=9, height=9)
    _put(engine, heads=[(0, 1), (8, 7)], directions=[3, 1])

    engine.step({})

    assert engine.get_winner() is None
    assert [crash["reasons"] for crash in engine.crashes] == [["wall"], ["wall"]]
    assert "simultaneous crash" in engine.summary()


def test_clean_final_tick_produces_duration_draw() -> None:
    engine = _engine(max_ticks=1)

    engine.step({0: {"turn": "left"}, 1: {"turn": "right"}})

    assert engine.is_terminal()
    assert engine.get_winner() is None
    assert engine.crashes == []
    assert engine.alive == [True, True]
    assert "tick-limit draw" in engine.summary()
    assert engine.get_legal_actions(0) == []


def test_collision_takes_precedence_over_tick_limit() -> None:
    engine = _engine(width=9, height=9, max_ticks=1)
    _put(engine, heads=[(0, 2), (6, 6)], directions=[3, 1])

    engine.step({})

    assert engine.get_winner() == [1]


def test_terminal_step_is_strictly_immutable() -> None:
    engine = _engine(max_ticks=1)
    engine.step({0: {"turn": "left"}, 1: {"turn": "right"}})
    before = (
        engine.get_render_data(),
        engine.observe(),
        engine.get_winner(),
        engine.rng.getstate(),
    )

    engine.step({0: {"turn": "right"}, 1: {"turn": "left"}})

    assert (
        engine.get_render_data(),
        engine.observe(),
        engine.get_winner(),
        engine.rng.getstate(),
    ) == before


def test_same_seed_and_actions_have_identical_replay_state() -> None:
    actions = [
        {0: {"turn": "left"}, 1: {"turn": "right"}},
        {0: {"turn": "straight"}, 1: {"turn": "straight"}},
        {0: {"turn": "right"}, 1: {"turn": "left"}},
        {0: {"turn": "straight"}, 1: {"turn": "straight"}},
    ]

    def play() -> list[dict[str, Any]]:
        game = _engine(engine_seed=98)
        frames = [game.get_render_data()]
        for move in actions:
            game.step(move)
            frames.append(game.get_render_data())
        return frames

    assert play() == play()


def test_reset_restores_initial_state_and_replay() -> None:
    engine = _engine(engine_seed=23)
    initial = engine.get_render_data()
    moves = {0: {"turn": "left"}, 1: {"turn": "right"}}
    engine.step(moves)
    first_frame = engine.get_render_data()

    engine.reset()
    assert engine.get_render_data() == initial
    assert not engine.is_terminal()
    assert engine.get_winner() is None
    engine.step(moves)
    assert engine.get_render_data() == first_frame


def test_observation_render_and_scores_are_defensive_copies() -> None:
    engine = _engine()
    engine.step({0: {"turn": "left"}, 1: {"turn": "right"}})
    observation = engine.observe()
    render = engine.get_render_data()
    scores = engine.get_scores()

    observation["state"]["heads"][0][0] = -99
    observation["state"]["trails"][0].clear()
    observation["legal_actions"][0][0]["turn"] = "teleport"
    observation["last_move"]["targets"][0][0] = -99
    render["heads"][0][0] = -99
    render["trails"][0].clear()
    scores["alive"][0] = False

    assert engine.heads[0][0] >= 0
    assert engine.trails[0]
    assert engine.get_legal_actions(0)[0] == {"turn": "left"}
    assert engine.last_move is not None and engine.last_move["targets"][0][0] >= 0
    assert engine.alive[0]


def test_state_remains_in_bounds_and_trails_never_overlap_during_play() -> None:
    engine = _engine(width=21, height=17, max_ticks=500)
    turn_cycle = ("left", "straight", "right", "straight")

    while not engine.is_terminal():
        turn = turn_cycle[engine.tick % len(turn_cycle)]
        engine.step({0: {"turn": turn}, 1: {"turn": turn}})
        for trail in engine.trails:
            for column, row in trail:
                assert 0 <= column < engine.config["width"]
                assert 0 <= row < engine.config["height"]
        flattened = [cell for trail in engine.trails for cell in trail]
        assert len(flattened) == len(set(flattened)) == len(engine._occupied)
        assert engine.tick <= engine.config["max_ticks"]


def test_legal_action_contract_is_small_and_exact() -> None:
    engine = _engine()
    expected = [{"turn": "left"}, {"turn": "straight"}, {"turn": "right"}]

    assert engine.get_legal_actions(0) == expected
    assert engine.get_legal_actions(1) == expected
    assert engine.get_legal_actions(-1) == []
    assert engine.observe()["legal_actions"] == [expected, expected]
