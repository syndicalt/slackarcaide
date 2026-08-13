"""Adversarial contract tests for canonical Ultimate Tic-Tac-Toe."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.engine.base import IllegalMove
from app.engine.games.ultimate_ttt import (
    MAX_PLACEMENTS,
    SIZE,
    UltimateTicTacToe,
)

SEATS = [{"seat": 0}, {"seat": 1}]
NO_CLOCK = {"time_control": {"base_sec": 300, "increment_sec": 2, "enabled": False}}
LINES = (
    ((0, 0), (0, 1), (0, 2)),
    ((1, 0), (1, 1), (1, 2)),
    ((2, 0), (2, 1), (2, 2)),
    ((0, 0), (1, 0), (2, 0)),
    ((0, 1), (1, 1), (2, 1)),
    ((0, 2), (1, 2), (2, 2)),
    ((0, 0), (1, 1), (2, 2)),
    ((0, 2), (1, 1), (2, 0)),
)
DRAW_PATTERN = (
    (0, 1, 0),
    (0, 1, 1),
    (1, 0, 0),
)


def _game(**config: Any) -> UltimateTicTacToe:
    return UltimateTicTacToe(config={**NO_CLOCK, **config}, seed=37, seats=list(SEATS))


def _place(game: UltimateTicTacToe, row: int, column: int) -> None:
    game.apply_action({"row": row, "column": column})


def _write_local(
    game: UltimateTicTacToe,
    local_row: int,
    local_column: int,
    pattern: tuple[tuple[int, ...], ...],
) -> None:
    for cell_row, values in enumerate(pattern):
        for cell_column, value in enumerate(values):
            game.board[local_row * 3 + cell_row][local_column * 3 + cell_column] = value


def test_initial_legal_actions_are_exact_row_major_and_seat_scoped() -> None:
    game = _game()

    actions = game.get_legal_actions(0)
    assert len(actions) == 82
    assert actions[:4] == [
        {"row": 0, "column": 0},
        {"row": 0, "column": 1},
        {"row": 0, "column": 2},
        {"row": 0, "column": 3},
    ]
    assert actions[-2:] == [{"row": 8, "column": 8}, {"resign": True}]
    assert game.get_legal_actions(1) == []
    assert game.get_legal_actions(True) == []
    assert game.get_legal_actions("0") == []  # type: ignore[arg-type]


def test_destination_routes_opponent_and_exposes_only_that_board() -> None:
    game = _game()
    _place(game, 0, 4)

    assert game.active_board == (0, 1)
    assert game.current_seat() == 1
    assert game.last_move == {
        "event": "place",
        "seat": 0,
        "row": 0,
        "column": 4,
        "local_board": [0, 1],
        "local_result": None,
        "next_board": [0, 1],
        "move": 1,
    }
    assert game.get_legal_actions(1) == [
        *(
            {"row": row, "column": column}
            for row in range(3)
            for column in range(3, 6)
            if (row, column) != (0, 4)
        ),
        {"resign": True},
    ]


def test_completed_destination_releases_opponent_to_any_unfinished_board() -> None:
    game = _game()
    game.local_results[0][1] = "draw"
    game.active_board = (1, 0)

    _place(game, 3, 1)

    assert game.active_board is None
    legal = game.get_legal_actions(1)
    assert {"row": 0, "column": 0} in legal
    assert {"row": 8, "column": 8} in legal
    assert not any(
        "row" in action and int(action["row"]) < 3 and 3 <= int(action["column"]) < 6
        for action in legal
    )


def test_wrong_or_completed_local_board_and_occupied_cell_are_transactional() -> None:
    game = _game()
    game.active_board = (1, 1)

    before = game.get_render_data()
    with pytest.raises(IllegalMove) as error:
        _place(game, 0, 0)
    assert error.value.code == "wrong_local_board"
    assert game.get_render_data() == before

    game.local_results[1][1] = 0
    game.active_board = None
    before = game.get_render_data()
    with pytest.raises(IllegalMove) as error:
        _place(game, 4, 4)
    assert error.value.code == "local_board_complete"
    assert game.get_render_data() == before

    game.local_results[1][1] = None
    game.board[4][4] = 1
    before = game.get_render_data()
    with pytest.raises(IllegalMove) as error:
        _place(game, 4, 4)
    assert error.value.code == "occupied_position"
    assert game.get_render_data() == before


@pytest.mark.parametrize("line", LINES, ids=[f"line-{index}" for index in range(8)])
def test_local_wins_in_every_orientation(line: tuple[tuple[int, int], ...]) -> None:
    game = _game()
    local_board = (1, 1)
    game.active_board = local_board
    for cell_row, cell_column in line[:2]:
        game.board[3 + cell_row][3 + cell_column] = 0
    final_row, final_column = line[2]

    _place(game, 3 + final_row, 3 + final_column)

    assert game.local_results[1][1] == 0
    assert game.last_move["local_result"] == 0
    assert not game.is_terminal()


@pytest.mark.parametrize("line", LINES, ids=[f"line-{index}" for index in range(8)])
def test_global_wins_in_every_orientation(line: tuple[tuple[int, int], ...]) -> None:
    game = _game()
    for local_row, local_column in line[:2]:
        game.local_results[local_row][local_column] = 0
    final_local_row, final_local_column = line[2]
    game.active_board = (final_local_row, final_local_column)
    base_row = final_local_row * 3
    base_column = final_local_column * 3
    game.board[base_row][base_column] = 0
    game.board[base_row][base_column + 1] = 0

    _place(game, base_row, base_column + 2)

    assert game.is_terminal()
    assert game.get_winner() == [0]
    assert game.active_board is None
    assert game.last_move["next_board"] is None
    assert game.local_results[final_local_row][final_local_column] == 0
    assert game.summary() == "Ultimate Tic-Tac-Toe — player 0 wins"


def test_drawn_local_board_blocks_global_line() -> None:
    game = _game()
    game.local_results = [[0, 0, "draw"], [None, None, None], [None, None, None]]

    assert UltimateTicTacToe._line_winner(game.local_results) is None
    assert not game.is_terminal()


def test_all_local_boards_complete_draws_on_exact_81st_placement() -> None:
    game = _game()
    completed = 0
    for local_row in range(3):
        for local_column in range(3):
            if (local_row, local_column) == (2, 2):
                continue
            pattern = DRAW_PATTERN if completed % 2 == 0 else tuple(
                tuple(1 - value for value in row) for row in DRAW_PATTERN
            )
            _write_local(game, local_row, local_column, pattern)
            game.local_results[local_row][local_column] = "draw"
            completed += 1

    for row in range(3):
        for column in range(3):
            if (row, column) != (2, 2):
                game.board[6 + row][6 + column] = DRAW_PATTERN[row][column]
    game.active_board = (2, 2)
    game.move_count = 80

    _place(game, 8, 8)

    assert game.move_count == MAX_PLACEMENTS
    assert game.local_results == [["draw"] * 3 for _ in range(3)]
    assert game.is_terminal()
    assert game.get_winner() is None
    assert game.summary() == "Ultimate Tic-Tac-Toe — draw"
    assert game.get_legal_actions(game.current_seat()) == []
    assert game.get_scores() == {
        "local_wins": [0, 0],
        "local_draws": 9,
        "placements": [41, 40],
        "moves": 81,
        "empty": 0,
    }


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (None, "invalid_action"),
        ("0,0", "invalid_action"),
        ({}, "invalid_action"),
        ({"row": 0}, "invalid_action"),
        ({"row": 0, "column": 0, "extra": 1}, "invalid_action"),
        ({"resign": False}, "invalid_action"),
        ({"resign": 1}, "invalid_action"),
        ({"row": True, "column": 0}, "invalid_position"),
        ({"row": 0, "column": False}, "invalid_position"),
        ({"row": 0.0, "column": 0}, "invalid_position"),
        ({"row": "0", "column": 0}, "invalid_position"),
        ({"row": -1, "column": 0}, "invalid_position"),
        ({"row": 0, "column": SIZE}, "invalid_position"),
    ],
)
def test_malformed_actions_never_mutate_state(action: Any, code: str) -> None:
    game = _game()
    before = deepcopy(game.get_render_data())

    with pytest.raises(IllegalMove) as error:
        game.apply_action(action)

    assert error.value.code == code
    assert game.get_render_data() == before
    assert game.move_count == 0


def test_observation_and_render_payloads_are_defensive_copies() -> None:
    game = _game()
    _place(game, 4, 4)
    observation = game.observe()
    render = game.get_render_data()

    observation["state"]["board"][4][4] = None
    observation["state"]["local_results"][1][1] = "draw"
    observation["state"]["active_board"][0] = 8
    observation["last_move"]["local_board"][0] = 8
    render["board"][4][4] = None
    render["local_results"][1][1] = "draw"
    render["active_board"][0] = 8
    render["last_move"]["next_board"][0] = 8

    assert game.board[4][4] == 0
    assert game.local_results[1][1] is None
    assert game.active_board == (1, 1)
    assert game.last_move["local_board"] == [1, 1]
    assert game.last_move["next_board"] == [1, 1]


def test_resignation_and_terminal_state_are_immutable() -> None:
    game = _game()
    game.apply_action({"resign": True})
    terminal = game.get_render_data()

    assert game.get_winner() == [1]
    assert game.move_count == 1
    assert game.summary() == "Ultimate Tic-Tac-Toe — player 0 resigns; player 1 wins"
    with pytest.raises(IllegalMove) as error:
        _place(game, 0, 0)
    assert error.value.code == "game_over"
    assert game.get_render_data() == terminal


def test_reset_and_replay_are_deterministic() -> None:
    actions = ((0, 0), (1, 1), (3, 3), (0, 1), (0, 3), (1, 0))
    first = _game()
    second = _game()
    for action in actions:
        _place(first, *action)
        _place(second, *action)

    expected = first.observe()
    assert second.observe() == expected
    first.reset()
    assert first.move_count == 0
    assert first.active_board is None
    assert all(cell is None for row in first.board for cell in row)
    for action in actions:
        _place(first, *action)
    assert first.observe() == expected


def test_strict_config_seats_seed_and_expired_clock() -> None:
    with pytest.raises(ValidationError):
        UltimateTicTacToe(config={"ranked": 1}, seed=1, seats=list(SEATS))
    with pytest.raises(ValidationError):
        UltimateTicTacToe(config={"unknown": 1}, seed=1, seats=list(SEATS))
    with pytest.raises(ValidationError):
        UltimateTicTacToe(
            config={"time_control": {"base_sec": 0, "increment_sec": 0, "enabled": True}},
            seed=1,
            seats=list(SEATS),
        )
    with pytest.raises(ValueError, match="expected 2 seats"):
        UltimateTicTacToe(config=NO_CLOCK, seed=1, seats=[{"seat": 0}])
    with pytest.raises(ValueError, match="seed"):
        UltimateTicTacToe(config=NO_CLOCK, seed=True, seats=list(SEATS))

    game = UltimateTicTacToe(config={}, seed=1, seats=list(SEATS))
    game._clock_remaining_ms[0] = 0
    with pytest.raises(IllegalMove) as error:
        _place(game, 0, 0)
    assert error.value.code == "clock_expired"
    assert game.move_count == 0
    game.timeout_loss(0)
    assert game.get_winner() == [1]
    assert game.get_legal_actions(0) == []
