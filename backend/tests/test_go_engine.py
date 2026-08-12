"""Adversarial rules tests for SlackArcade's fixed 9x9 Go variant."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.engine.base import IllegalMove
from app.engine.games.go import BLACK, BOARD_SIZE, EMPTY, WHITE, Go

SEATS = [{"seat": 0}, {"seat": 1}]


def _go(**config: object) -> Go:
    config.setdefault("time_control", {"enabled": False})
    return Go(config=config, seed=17, seats=list(SEATS))


def _set_position(engine: Go, stones: dict[tuple[int, int], int], *, turn: int = 0) -> None:
    engine.board = [[EMPTY for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    for (row, column), color in stones.items():
        engine.board[row][column] = color
    engine.move_count = turn
    engine.consecutive_passes = 0
    engine.captures = {0: 0, 1: 0}
    engine.last_move = None
    engine._position_history = {engine._position(engine.board)}


def _assert_code(engine: Go, action: object, code: str) -> None:
    with pytest.raises(IllegalMove) as exc_info:
        engine.apply_action(action)
    assert exc_info.value.code == code


def _snapshot(engine: Go) -> dict[str, object]:
    state = deepcopy({key: value for key, value in engine.__dict__.items() if key != "rng"})
    state["rng_state"] = engine.rng.getstate()
    return state


def test_initial_contract_and_legal_actions_are_complete() -> None:
    engine = _go()
    assert engine.current_seat() == 0
    assert engine.get_scores() == {
        "black": {"stones": 0, "territory": 0, "komi": 0.0, "total": 0.0, "captures": 0},
        "white": {"stones": 0, "territory": 0, "komi": 7.5, "total": 7.5, "captures": 0},
    }
    legal = engine.get_legal_actions(0)
    assert len(legal) == 83
    assert {"row": 0, "column": 0} in legal
    assert {"row": 8, "column": 8} in legal
    assert {"pass": True} in legal
    assert {"resign": True} in legal
    assert engine.get_legal_actions(1) == []

    engine.apply_action({"row": 4, "column": 4})
    assert {"row": 4, "column": 4} not in engine.get_legal_actions(1)
    assert len(engine.get_legal_actions(1)) == 82


def test_single_stone_capture_and_area_score_does_not_add_captures() -> None:
    engine = _go()
    engine.apply_action({"row": 0, "column": 1})
    engine.apply_action({"row": 0, "column": 0})
    engine.apply_action({"row": 1, "column": 0})

    assert engine.board[0][0] == EMPTY
    scores = engine.get_scores()
    assert scores["black"] == {
        "stones": 2,
        "territory": 79,
        "komi": 0.0,
        "total": 81.0,
        "captures": 1,
    }
    # Regression: capture count is metadata, not a component of area score.
    assert scores["black"]["total"] == scores["black"]["stones"] + scores["black"]["territory"]


def test_multi_stone_capture() -> None:
    engine = _go()
    _set_position(
        engine,
        {
            (0, 0): WHITE,
            (0, 1): WHITE,
            (1, 0): BLACK,
            (1, 1): BLACK,
        },
    )
    engine.apply_action({"row": 0, "column": 2})
    assert engine.board[0][0] == EMPTY
    assert engine.board[0][1] == EMPTY
    assert engine.captures == {0: 2, 1: 0}


def test_suicide_is_rejected_without_mutation() -> None:
    engine = _go()
    _set_position(
        engine,
        {
            (0, 1): WHITE,
            (1, 0): WHITE,
            (1, 2): WHITE,
            (2, 1): WHITE,
        },
    )
    before = _snapshot(engine)
    _assert_code(engine, {"row": 1, "column": 1}, "suicide")
    assert _snapshot(engine) == before
    assert {"row": 1, "column": 1} not in engine.get_legal_actions(0)


def test_surrounded_placement_is_legal_when_it_captures_and_survives() -> None:
    engine = _go()
    _set_position(
        engine,
        {
            (0, 1): WHITE,
            (1, 0): WHITE,
            (0, 2): BLACK,
            (1, 1): BLACK,
            (2, 0): BLACK,
        },
    )
    engine.apply_action({"row": 0, "column": 0})
    assert engine.board[0][0] == BLACK
    assert engine.board[0][1] == EMPTY
    assert engine.board[1][0] == EMPTY
    assert engine.captures[0] == 2


def test_immediate_ko_recapture_is_rejected_transactionally() -> None:
    engine = _go()
    _set_position(
        engine,
        {
            (0, 1): BLACK,
            (1, 0): BLACK,
            (2, 1): BLACK,
            (1, 1): WHITE,
            (0, 2): WHITE,
            (1, 3): WHITE,
            (2, 2): WHITE,
        },
    )
    original = engine._position(engine.board)
    engine.apply_action({"row": 1, "column": 2})
    assert engine.board[1][1] == EMPTY
    assert engine.captures[0] == 1

    before = _snapshot(engine)
    _assert_code(engine, {"row": 1, "column": 1}, "superko")
    assert _snapshot(engine) == before
    assert engine._position(engine.board) != original


def test_positional_superko_checks_all_history_not_only_previous_board() -> None:
    engine = _go()
    repeated = [[EMPTY for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]
    repeated[4][4] = BLACK
    # Model a position seen much earlier, while the current empty board is the
    # immediately preceding one. The placement must still be rejected.
    engine._position_history.add(engine._position(repeated))
    before = _snapshot(engine)
    _assert_code(engine, {"row": 4, "column": 4}, "superko")
    assert _snapshot(engine) == before


def test_pass_does_not_poison_superko_and_placement_resets_pass_count() -> None:
    engine = _go()
    engine.apply_action({"pass": True})
    assert engine.consecutive_passes == 1
    assert len(engine._position_history) == 1

    engine.apply_action({"row": 4, "column": 4})
    assert not engine.is_terminal()
    assert engine.consecutive_passes == 0
    assert len(engine._position_history) == 2

    engine.apply_action({"pass": True})
    assert not engine.is_terminal()
    engine.apply_action({"pass": True})
    assert engine.is_terminal()


def test_area_scoring_counts_living_stones_and_exclusive_territory_only() -> None:
    engine = _go(komi=0.0)
    _set_position(
        engine,
        {
            (1, 2): BLACK,
            (2, 1): BLACK,
            (2, 3): BLACK,
            (3, 2): BLACK,
            (5, 6): WHITE,
            (6, 5): WHITE,
            (6, 7): WHITE,
            (7, 6): WHITE,
        },
    )
    scores = engine.get_scores()
    assert scores["black"] == {
        "stones": 4,
        "territory": 1,
        "komi": 0.0,
        "total": 5.0,
        "captures": 0,
    }
    assert scores["white"] == {
        "stones": 4,
        "territory": 1,
        "komi": 0.0,
        "total": 5.0,
        "captures": 0,
    }
    # The large outside region touches both colors and is neutral.
    assert scores["black"]["territory"] + scores["white"]["territory"] == 2


def test_komi_decides_empty_board_after_two_passes() -> None:
    engine = _go()
    engine.apply_action({"pass": True})
    engine.apply_action({"pass": True})
    assert engine.is_terminal()
    assert engine.get_winner() == [1]
    assert engine.get_scores()["white"]["total"] == 7.5
    assert "White wins" in engine.summary()


def test_zero_komi_can_draw() -> None:
    engine = _go(komi=0.0)
    engine.apply_action({"pass": True})
    engine.apply_action({"pass": True})
    assert engine.is_terminal()
    assert engine.get_winner() is None
    assert "draw" in engine.summary()


def test_resignation_and_terminal_state_are_immutable() -> None:
    engine = _go()
    engine.apply_action({"resign": True})
    assert engine.is_terminal()
    assert engine.get_winner() == [1]
    assert engine.last_move == {"event": "resign", "seat": 0, "move": 1}
    before = _snapshot(engine)
    _assert_code(engine, {"pass": True}, "game_over")
    assert _snapshot(engine) == before


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (None, "invalid_action"),
        ([], "invalid_action"),
        ({}, "invalid_action"),
        ({"pass": False}, "invalid_action"),
        ({"pass": 1}, "invalid_action"),
        ({"resign": False}, "invalid_action"),
        ({"resign": 1}, "invalid_action"),
        ({"pass": True, "resign": True}, "invalid_action"),
        ({"row": 0, "column": 0, "extra": 1}, "invalid_action"),
        ({"row": True, "column": 0}, "invalid_coordinate"),
        ({"row": 0, "column": False}, "invalid_coordinate"),
        ({"row": 1.0, "column": 0}, "invalid_coordinate"),
        ({"row": "1", "column": 0}, "invalid_coordinate"),
        ({"row": -1, "column": 0}, "out_of_bounds"),
        ({"row": 0, "column": 9}, "out_of_bounds"),
    ],
)
def test_malformed_actions_have_stable_errors_and_do_not_mutate(action: object, code: str) -> None:
    engine = _go()
    before = _snapshot(engine)
    _assert_code(engine, action, code)
    assert _snapshot(engine) == before


def test_occupied_intersection_is_rejected_without_mutation() -> None:
    engine = _go()
    engine.apply_action({"row": 3, "column": 3})
    before = _snapshot(engine)
    _assert_code(engine, {"row": 3, "column": 3}, "occupied")
    assert _snapshot(engine) == before


@pytest.mark.parametrize(
    "config",
    [
        {"board_size": 13},
        {"board_size": True},
        {"komi": 7},
        {"komi": float("inf")},
        {"max_moves": 1},
        {"max_moves": 513},
        {"max_moves": 511},
        {"max_moves": True},
        {"ranked": 1},
        {"unknown": "value"},
        {"time_control": {"enabled": False, "extra": 1}},
    ],
)
def test_config_is_strict_and_bounded(config: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _go(**config)


def test_max_move_cap_uses_area_score() -> None:
    engine = _go(max_moves=2)
    engine.apply_action({"row": 0, "column": 0})
    engine.apply_action({"row": 8, "column": 8})
    assert engine.is_terminal()
    assert engine.move_count == 2
    assert engine.get_winner() == [1]  # one stone each; White has komi


def test_reset_and_replay_are_deterministic() -> None:
    actions = [
        {"row": 2, "column": 2},
        {"row": 6, "column": 6},
        {"pass": True},
        {"row": 4, "column": 4},
    ]
    first = _go()
    for action in actions:
        first.apply_action(action)
    expected = {
        "observation": first.observe(),
        "render": first.get_render_data(),
        "winner": first.get_winner(),
    }

    first.reset()
    for action in actions:
        first.apply_action(action)
    replayed = {
        "observation": first.observe(),
        "render": first.get_render_data(),
        "winner": first.get_winner(),
    }
    second = _go()
    for action in actions:
        second.apply_action(action)

    assert replayed == expected
    assert second.observe() == expected["observation"]


def test_render_and_observation_return_detached_board_data() -> None:
    engine = _go()
    engine.apply_action({"row": 4, "column": 4})
    rendered = engine.get_render_data()
    observed = engine.observe()
    rendered["board"][0][0] = "black"
    observed["state"]["board"][0][1] = BLACK
    rendered["last_move"]["row"] = 0
    observed["last_move"]["column"] = 0
    assert engine.board[0][0] == EMPTY
    assert engine.board[0][1] == EMPTY
    assert engine.last_move["row"] == 4
    assert engine.last_move["column"] == 4
