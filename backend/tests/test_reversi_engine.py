"""Adversarial contract tests for standard two-player Reversi."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.engine.base import IllegalMove
from app.engine.games.reversi import SIZE, Reversi

SEATS = [{"seat": 0}, {"seat": 1}]
NO_CLOCK = {"time_control": {"base_sec": 600, "increment_sec": 2, "enabled": False}}


def _game(**config: Any) -> Reversi:
    return Reversi(config={**NO_CLOCK, **config}, seed=29, seats=list(SEATS))


def _play(game: Reversi, *placements: tuple[int, int]) -> None:
    for row, column in placements:
        game.apply_action({"row": row, "column": column})


def test_standard_opening_and_single_direction_flip() -> None:
    game = _game()

    assert game.current_seat() == 0
    assert game.get_scores() == {"disks": [2, 2], "empty": 60, "moves": 0}
    assert game.get_legal_actions(0) == [
        {"row": 2, "column": 3},
        {"row": 3, "column": 2},
        {"row": 4, "column": 5},
        {"row": 5, "column": 4},
        {"resign": True},
    ]
    assert game.get_legal_actions(1) == []

    game.apply_action({"row": 2, "column": 3})
    assert game.current_seat() == 1
    assert game.board[2][3] == game.board[3][3] == 0
    assert game.get_scores() == {"disks": [4, 1], "empty": 59, "moves": 1}
    assert game.last_move["flipped_positions"] == [[3, 3]]


def test_one_placement_flips_all_eight_bracketed_directions() -> None:
    game = _game()
    game.board = [[None for _ in range(SIZE)] for _ in range(SIZE)]
    for row_step, column_step in (
        (-1, -1),
        (-1, 0),
        (-1, 1),
        (0, -1),
        (0, 1),
        (1, -1),
        (1, 0),
        (1, 1),
    ):
        game.board[3 + row_step][3 + column_step] = 1
        game.board[3 + 2 * row_step][3 + 2 * column_step] = 0

    game.apply_action({"row": 3, "column": 3})

    assert game.last_move["flipped"] == 8
    assert len(game.last_move["flipped_positions"]) == 8
    assert all(
        game.board[3 + row_step][3 + column_step] == 0
        for row_step, column_step in (
            (-1, -1),
            (-1, 0),
            (-1, 1),
            (0, -1),
            (0, 1),
            (1, -1),
            (1, 0),
            (1, 1),
        )
    )


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (None, "invalid_action"),
        ("d3", "invalid_action"),
        ({}, "invalid_action"),
        ({"row": 2}, "invalid_action"),
        ({"row": 2, "column": 3, "ignored": True}, "invalid_action"),
        ({"resign": False}, "invalid_action"),
        ({"row": True, "column": 3}, "invalid_position"),
        ({"row": 2, "column": False}, "invalid_position"),
        ({"row": 2.0, "column": 3}, "invalid_position"),
        ({"row": "2", "column": 3}, "invalid_position"),
        ({"row": -1, "column": 3}, "invalid_position"),
        ({"row": 2, "column": SIZE}, "invalid_position"),
        ({"row": 3, "column": 3}, "occupied_position"),
        ({"row": 0, "column": 0}, "no_capture"),
    ],
)
def test_rejects_malformed_or_non_capturing_actions_without_mutation(
    action: Any, code: str
) -> None:
    game = _game()
    before = game.get_render_data()

    with pytest.raises(IllegalMove) as error:
        game.apply_action(action)

    assert error.value.code == code
    assert game.get_render_data() == before
    assert game.move_count == 0


def test_forced_pass_is_automatic_and_same_player_moves_again() -> None:
    game = _game()
    prefix = (
        (2, 3),
        (2, 2),
        (2, 1),
        (1, 1),
        (0, 1),
        (0, 0),
        (3, 2),
        (0, 2),
        (1, 2),
        (1, 3),
        (0, 3),
        (0, 4),
        (1, 0),
        (2, 0),
        (4, 5),
        (1, 4),
        (0, 5),
    )
    _play(game, *prefix)
    mover = game.current_seat()
    game.apply_action({"row": 0, "column": 6})

    assert mover == 1
    assert game.current_seat() == mover
    assert game.last_move["passed_seat"] == 0
    assert game._legal_placements(0) == []
    assert game._legal_placements(1)
    assert "player 0 passed" in game.summary()


def test_double_pass_ends_game_before_board_is_full() -> None:
    game = _game()
    game.board = [[0 for _ in range(SIZE)] for _ in range(SIZE)]
    game.board[0][0] = None
    game.board[0][1] = 1
    game.board[7][7] = None
    game.move_count = 58
    game._current_seat = 0

    game.apply_action({"row": 0, "column": 0})

    assert game.is_terminal()
    assert game.move_count == 59
    assert game.get_winner() == [0]
    assert game.get_scores() == {"disks": [63, 0], "empty": 1, "moves": 59}
    assert game.get_legal_actions(game.current_seat()) == []


def test_equal_disk_count_is_a_draw() -> None:
    game = _game()
    # Reachable position after 59 placements. Black's only empty square flips
    # five white disks, producing 32 disks per side.
    encoded_rows = (
        "00000010",
        "11100000",
        ".1011000",
        "11110011",
        "11110011",
        "11100111",
        "11001011",
        "11111101",
    )
    game.board = [
        [None if disk == "." else int(disk) for disk in encoded_row] for encoded_row in encoded_rows
    ]
    game.move_count = 59
    game._current_seat = 0

    game.apply_action({"row": 2, "column": 0})

    assert game.get_scores() == {"disks": [32, 32], "empty": 0, "moves": 60}
    assert game.get_winner() is None
    assert game.summary() == "Reversi — draw, 32-32"


def test_full_deterministic_game_scores_winner_and_replays_identically() -> None:
    first = _game()
    actions: list[tuple[int, int]] = []
    while not first.is_terminal():
        action = next(
            candidate
            for candidate in first.get_legal_actions(first.current_seat())
            if "row" in candidate
        )
        placement = (int(action["row"]), int(action["column"]))
        actions.append(placement)
        first.apply_action(action)

    second = _game()
    _play(second, *actions)
    assert len(actions) <= 60
    assert second.get_render_data() == first.get_render_data()
    assert second.get_scores() == first.get_scores()
    assert second.get_winner() == first.get_winner()
    assert second.summary() == first.summary()

    first.reset()
    _play(first, *actions)
    assert first.get_render_data() == second.get_render_data()


def test_observations_do_not_expose_mutable_engine_state() -> None:
    game = _game()
    game.apply_action({"row": 2, "column": 3})
    observation = game.observe()
    render = game.get_render_data()

    observation["state"]["board"][2][3] = None
    observation["last_move"]["flipped_positions"].clear()
    render["board"][3][3] = 1

    assert game.board[2][3] == 0
    assert game.board[3][3] == 0
    assert game.last_move["flipped_positions"] == [[3, 3]]


def test_resignation_terminal_immutability_strict_config_and_clock() -> None:
    game = _game()
    game.apply_action({"resign": True})
    terminal = game.get_render_data()
    assert game.get_winner() == [1]
    with pytest.raises(IllegalMove) as error:
        game.apply_action({"row": 2, "column": 3})
    assert error.value.code == "game_over"
    assert game.get_render_data() == terminal

    with pytest.raises(ValidationError):
        Reversi(config={"ranked": 1}, seed=1, seats=list(SEATS))
    with pytest.raises(ValidationError):
        Reversi(config={"unknown": True}, seed=1, seats=list(SEATS))
    with pytest.raises(ValueError, match="ordered and numbered"):
        Reversi(config=NO_CLOCK, seed=1, seats=[{"seat": 1}, {"seat": 0}])

    clocked = Reversi(config={}, seed=1, seats=list(SEATS))
    clocked._clock_remaining_ms[0] = 0
    with pytest.raises(IllegalMove) as expired:
        clocked.apply_action({"row": 2, "column": 3})
    assert expired.value.code == "clock_expired"
    clocked.timeout_loss(0)
    assert clocked.get_winner() == [1]
