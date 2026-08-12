"""Adversarial contract tests for the bounded Connect Four engine."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.engine.base import IllegalMove
from app.engine.games.connect_four import COLUMNS, ROWS, ConnectFour

SEATS = [{"seat": 0}, {"seat": 1}]
NO_CLOCK = {"time_control": {"base_sec": 300, "increment_sec": 2, "enabled": False}}


def _game(**config: Any) -> ConnectFour:
    return ConnectFour(config={**NO_CLOCK, **config}, seed=17, seats=list(SEATS))


def _drop(game: ConnectFour, *columns: int) -> None:
    for column in columns:
        game.apply_action({"column": column})


@pytest.mark.parametrize(
    "columns",
    [
        (0, 1, 0, 1, 0, 1, 0),
        (0, 0, 1, 1, 2, 2, 3),
        (0, 1, 1, 2, 6, 2, 2, 3, 6, 3, 5, 3, 3),
        (6, 5, 5, 4, 0, 4, 4, 3, 0, 3, 1, 3, 3),
    ],
    ids=("vertical", "horizontal", "down-right diagonal", "down-left diagonal"),
)
def test_detects_all_win_directions(columns: tuple[int, ...]) -> None:
    game = _game()
    _drop(game, *columns)

    assert game.is_terminal()
    assert game.get_winner() == [0]
    assert game.move_count == len(columns)
    assert "player 0 wins" in game.summary()


def test_gravity_legal_actions_and_observation_are_defensive_copies() -> None:
    game = _game()

    assert game.get_legal_actions(1) == []
    assert game.get_legal_actions(0) == [
        *({"column": column} for column in range(COLUMNS)),
        {"resign": True},
    ]
    _drop(game, 3, 3)
    assert game.board[ROWS - 1][3] == 0
    assert game.board[ROWS - 2][3] == 1
    assert game.last_move == {
        "event": "drop",
        "seat": 1,
        "row": ROWS - 2,
        "column": 3,
        "move": 2,
    }

    observation = game.observe()
    render = game.get_render_data()
    observation["state"]["board"][ROWS - 1][3] = None
    render["board"][ROWS - 2][3] = None
    assert game.board[ROWS - 1][3] == 0
    assert game.board[ROWS - 2][3] == 1


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (None, "invalid_action"),
        ("3", "invalid_action"),
        ({}, "invalid_action"),
        ({"column": 0, "ignored": True}, "invalid_action"),
        ({"resign": False}, "invalid_action"),
        ({"column": True}, "invalid_column"),
        ({"column": 1.0}, "invalid_column"),
        ({"column": "1"}, "invalid_column"),
        ({"column": -1}, "invalid_column"),
        ({"column": COLUMNS}, "invalid_column"),
    ],
)
def test_rejects_malformed_actions_without_mutating_state(action: Any, code: str) -> None:
    game = _game()
    before = game.get_render_data()

    with pytest.raises(IllegalMove) as error:
        game.apply_action(action)

    assert error.value.code == code
    assert game.get_render_data() == before
    assert game.move_count == 0


def test_full_column_is_rejected_and_removed_from_legal_actions() -> None:
    game = _game()
    _drop(game, 2, 2, 2, 2, 2, 2)

    assert {"column": 2} not in game.get_legal_actions(game.current_seat())
    before = game.get_render_data()
    with pytest.raises(IllegalMove, match="full") as error:
        game.apply_action({"column": 2})
    assert error.value.code == "column_full"
    assert game.get_render_data() == before


def test_known_full_board_sequence_is_a_draw() -> None:
    game = _game()
    draw = (
        4,
        3,
        6,
        0,
        1,
        4,
        5,
        5,
        1,
        1,
        5,
        0,
        1,
        6,
        0,
        1,
        5,
        5,
        1,
        0,
        4,
        6,
        3,
        2,
        6,
        6,
        0,
        4,
        6,
        5,
        2,
        0,
        4,
        2,
        4,
        2,
        2,
        2,
        3,
        3,
        3,
        3,
    )
    _drop(game, *draw)

    assert game.is_terminal()
    assert game.get_winner() is None
    assert game.get_scores() == {"tokens": [21, 21], "moves": 42, "empty": 0}
    assert game.get_legal_actions(game.current_seat()) == []
    assert game.summary() == "Connect Four — draw"


def test_resignation_and_terminal_state_are_immutable() -> None:
    game = _game()
    game.apply_action({"resign": True})
    terminal = game.get_render_data()

    assert game.get_winner() == [1]
    assert game.move_count == 1
    with pytest.raises(IllegalMove) as error:
        game.apply_action({"column": 0})
    assert error.value.code == "game_over"
    assert game.get_render_data() == terminal


def test_reset_and_replay_are_deterministic() -> None:
    actions = (4, 2, 4, 2, 5, 1)
    first = _game()
    second = _game()
    _drop(first, *actions)
    _drop(second, *actions)

    assert first.observe() == second.observe()
    expected = first.get_render_data()
    first.reset()
    assert first.move_count == 0
    assert all(cell is None for row in first.board for cell in row)
    _drop(first, *actions)
    assert first.get_render_data() == expected


def test_strict_config_seats_and_expired_clock() -> None:
    with pytest.raises(ValidationError):
        ConnectFour(config={"ranked": 1}, seed=1, seats=list(SEATS))
    with pytest.raises(ValidationError):
        ConnectFour(config={"unknown": 1}, seed=1, seats=list(SEATS))
    with pytest.raises(ValueError, match="expected 2 seats"):
        ConnectFour(config=NO_CLOCK, seed=1, seats=[{"seat": 0}])

    game = ConnectFour(config={}, seed=1, seats=list(SEATS))
    game._clock_remaining_ms[0] = 0
    with pytest.raises(IllegalMove) as error:
        game.apply_action({"column": 0})
    assert error.value.code == "clock_expired"
    game.timeout_loss(0)
    assert game.get_winner() == [1]
