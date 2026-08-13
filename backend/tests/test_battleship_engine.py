"""Adversarial tests for private-state Battleship."""

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.engine.base import IllegalMove
from app.engine.games.battleship import FLEET, Battleship

SEATS = [{"seat": 0, "agent_id": "alpha"}, {"seat": 1, "agent_id": "bravo"}]
NO_CLOCK = {"time_control": {"enabled": False}}


def _game(**config: Any) -> Battleship:
    merged = {**NO_CLOCK, **config}
    return Battleship(config=merged, seed=29, seats=deepcopy(SEATS))


def _fleet(*, vertical: bool = False, offset: int = 0) -> dict[str, Any]:
    ships: list[dict[str, Any]] = []
    for index, (ship_id, _length) in enumerate(FLEET):
        if vertical:
            start = {"row": 0, "column": 9 - index - offset}
            orientation = "vertical"
        else:
            start = {"row": index + offset, "column": 0}
            orientation = "horizontal"
        ships.append({"id": ship_id, "start": start, "orientation": orientation})
    return {"ships": ships}


def _place_both(game: Battleship) -> None:
    game.apply_action(_fleet())
    game.apply_action(_fleet(vertical=True))


def _public_board(observation: dict[str, Any], seat: int) -> dict[str, Any]:
    return next(board for board in observation["state"]["boards"] if board["seat"] == seat)


def test_initial_contract_is_bounded_and_first_player_is_deterministic() -> None:
    game = _game()
    legal = game.get_legal_actions(0)

    assert game.phase == "placement"
    assert game.current_seat() == 0
    assert game.legal_actions_exhaustive(0) is False
    assert len(legal) == 2
    assert legal[0]["$contract"] == "complete_fleet"
    assert [ship["id"] for ship in legal[0]["submit"]["ships"]] == [
        ship_id for ship_id, _length in FLEET
    ]
    assert game.get_legal_actions(1) == []
    assert game.get_legal_actions(True) == []


def test_complete_fleets_are_atomic_and_touching_is_allowed() -> None:
    game = _game()
    # Every horizontal fleet row is adjacent to the next; standard placement
    # permits both orthogonal and diagonal contact.
    game.apply_action(_fleet())
    assert game.fleets[0] is not None
    assert game.current_seat() == 1
    assert game.move_count == 1

    game.apply_action(_fleet(vertical=True))
    assert game.phase == "battle"
    assert game.current_seat() == 0
    assert game.move_count == 2
    assert game.legal_actions_exhaustive(0) is True
    assert len(game.get_legal_actions(0)) == 101


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (None, "invalid_action"),
        (lambda action: action.update(extra=True), "invalid_action"),
        (lambda action: action["ships"].pop(), "invalid_fleet"),
        (
            lambda action: action["ships"][0].update(id="destroyer"),
            "invalid_ship_order",
        ),
        (lambda action: action["ships"][0].update(extra=True), "invalid_ship"),
        (lambda action: action["ships"][0].update(start={"row": 0}), "invalid_ship"),
        (lambda action: action["ships"][0]["start"].update(row=True), "invalid_coordinate"),
        (lambda action: action["ships"][0]["start"].update(row=-1), "invalid_coordinate"),
        (
            lambda action: action["ships"][0].update(orientation="diagonal"),
            "invalid_orientation",
        ),
        (
            lambda action: action["ships"][0].update(
                start={"row": 0, "column": 6}, orientation="horizontal"
            ),
            "ship_out_of_bounds",
        ),
        (
            lambda action: action["ships"][1].update(
                start={"row": 0, "column": 0}, orientation="vertical"
            ),
            "ships_overlap",
        ),
    ],
)
def test_invalid_placement_payloads_leave_state_unchanged(mutate: Any, code: str) -> None:
    game = _game()
    action: Any = _fleet()
    if mutate is None:
        action = None
    else:
        mutate(action)
    snapshot = deepcopy(game.observe(0))

    with pytest.raises(IllegalMove) as error:
        game.apply_action(action)

    assert error.value.code == code
    assert game.observe(0) == snapshot
    assert game.fleets == [None, None]


def test_synchronous_placement_validation_is_transactional() -> None:
    game = _game()
    invalid = _fleet()
    invalid["ships"][1]["start"] = {"row": 0, "column": 0}
    snapshot = deepcopy(game.observe(0))

    with pytest.raises(IllegalMove) as error:
        game.validate_action(invalid, 0)
    assert error.value.code == "ships_overlap"
    assert game.observe(0) == snapshot

    game.validate_action(_fleet(), 0)
    assert game.observe(0) == snapshot
    assert game.fleets == [None, None]


def test_no_fleet_leakage_in_seat_or_public_observations_and_render() -> None:
    game = _game()
    game.apply_action(_fleet())

    public_during_placement = game.observe(None)
    assert "ships" not in _public_board(public_during_placement, 0)
    assert "ships" not in _public_board(public_during_placement, 1)
    assert game.last_move == {"event": "fleet_placed", "seat": 0, "move": 1}

    game.apply_action(_fleet(vertical=True))
    seat_zero = game.observe(0)
    seat_one = game.observe(1)
    public = game.observe(None)
    render = game.get_render_data()

    assert "ships" in _public_board(seat_zero, 0)
    assert "ships" not in _public_board(seat_zero, 1)
    assert "ships" not in _public_board(seat_one, 0)
    assert "ships" in _public_board(seat_one, 1)
    assert all("ships" not in board for board in public["state"]["boards"])
    assert all("ships" not in board for board in render["boards"])

    opponent_ship_records = _public_board(seat_one, 1)["ships"]
    opponent_secret_coordinates = {
        (cell["row"], cell["column"])
        for ship in opponent_ship_records
        for cell in ship["cells"]
    }
    seat_zero_visible_coordinates = {
        (cell["row"], cell["column"])
        for cell in _public_board(seat_zero, 1)["cells"]
    }
    assert opponent_secret_coordinates
    assert seat_zero_visible_coordinates == set()


def test_shots_reveal_only_observed_hit_or_miss_and_reject_duplicates() -> None:
    game = _game()
    _place_both(game)

    game.apply_action({"row": 0, "column": 9})
    game.apply_action({"row": 9, "column": 9})
    assert game.last_move["outcome"] == "miss"
    assert game.current_seat() == 0

    target = _public_board(game.observe(0), 1)
    assert target == {"seat": 1, "cells": [{"row": 0, "column": 9, "shot": "hit"}]}
    assert _public_board(game.observe(None), 1) == target
    assert "ships" not in target

    snapshot = deepcopy(game.observe(0))
    with pytest.raises(IllegalMove) as error:
        game.apply_action({"row": 0, "column": 9})
    assert error.value.code == "duplicate_shot"
    assert game.observe(0) == snapshot


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (None, "invalid_action"),
        ({}, "invalid_action"),
        ({"row": 0}, "invalid_action"),
        ({"row": 0, "column": 0, "extra": 1}, "invalid_action"),
        ({"row": True, "column": 0}, "invalid_coordinate"),
        ({"row": 0.0, "column": 0}, "invalid_coordinate"),
        ({"row": 0, "column": 10}, "invalid_coordinate"),
        ({"resign": False}, "invalid_action"),
        ({"resign": 1}, "invalid_action"),
    ],
)
def test_invalid_battle_payloads_do_not_advance(action: Any, code: str) -> None:
    game = _game()
    _place_both(game)
    snapshot = deepcopy(game.observe(0))

    with pytest.raises(IllegalMove) as error:
        game.apply_action(action)

    assert error.value.code == code
    assert game.observe(0) == snapshot


def test_every_ship_must_be_sunk_and_terminal_render_reveals_fleets() -> None:
    game = _game()
    _place_both(game)
    targets = [cell for ship in game.fleets[1].values() for cell in ship]  # type: ignore[union-attr]
    reply_misses = [(9, column) for column in range(10)] + [
        (8, column) for column in range(7)
    ]

    for index, (row, column) in enumerate(targets):
        game.apply_action({"row": row, "column": column})
        if index < len(targets) - 1:
            reply_row, reply_column = reply_misses[index]
            game.apply_action({"row": reply_row, "column": reply_column})
            assert not game.is_terminal()

    assert game.is_terminal()
    assert game.get_winner() == [0]
    assert game.get_scores()["ships_sunk"] == [5, 0]
    assert game.last_move["sunk"] == "destroyer"
    assert all("ships" in board for board in game.get_render_data()["boards"])
    assert all("ships" in board for board in game.observe(None)["state"]["boards"])

    terminal = deepcopy(game.get_render_data())
    with pytest.raises(IllegalMove) as error:
        game.apply_action({"row": 9, "column": 9})
    assert error.value.code == "game_over"
    assert game.get_render_data() == terminal


def test_resign_clock_timeout_reset_replay_and_defensive_copies() -> None:
    game = _game()
    game.apply_action(_fleet())
    game.apply_action({"resign": True})
    assert game.get_winner() == [0]
    assert "resignation" in game.summary()

    clocked = Battleship(config={}, seed=29, seats=deepcopy(SEATS))
    clocked._clock_remaining_ms[0] = 0
    with pytest.raises(IllegalMove) as error:
        clocked.apply_action(_fleet())
    assert error.value.code == "clock_expired"
    clocked.timeout_loss(0)
    assert clocked.get_winner() == [1]

    actions = [_fleet(), _fleet(vertical=True), {"row": 0, "column": 9}, {"row": 9, "column": 9}]
    first = _game()
    second = _game()
    for action in actions:
        first.apply_action(deepcopy(action))
        second.apply_action(deepcopy(action))
    expected = first.observe(0)
    assert expected == second.observe(0)

    observation = first.observe(0)
    render = first.get_render_data()
    observation["state"]["boards"].clear()
    observation["legal_actions"].clear()
    render["boards"].clear()
    assert first.observe(0) == expected

    first.reset()
    for action in actions:
        first.apply_action(deepcopy(action))
    assert first.observe(0) == expected


def test_strict_config_seats_and_perspective_validation() -> None:
    with pytest.raises(ValidationError):
        Battleship(config={"ranked": 1}, seed=1, seats=deepcopy(SEATS))
    with pytest.raises(ValidationError):
        Battleship(config={"board_size": 9}, seed=1, seats=deepcopy(SEATS))
    with pytest.raises(ValidationError):
        Battleship(config={"ships_may_touch": False}, seed=1, seats=deepcopy(SEATS))
    with pytest.raises(ValidationError):
        Battleship(config={"unknown": True}, seed=1, seats=deepcopy(SEATS))
    with pytest.raises(ValueError, match="expected 2 seats"):
        Battleship(config=NO_CLOCK, seed=1, seats=[{"seat": 0}])
    with pytest.raises(ValueError, match="ordered and numbered"):
        Battleship(config=NO_CLOCK, seed=1, seats=[{"seat": 1}, {"seat": 0}])

    game = _game()
    for perspective in (True, -1, 2, "0"):
        with pytest.raises(ValueError, match="perspective"):
            game.observe(perspective)  # type: ignore[arg-type]
