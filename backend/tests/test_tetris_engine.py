"""Adversarial contract tests for two-player Battle Tetris."""

from __future__ import annotations

import copy
import math
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.engine.games.tetris import (
    ATTACK_ROWS,
    CLEAR_POINTS,
    GARBAGE_CELL,
    PIECE_TYPES,
    SHAPES,
    Tetris,
)


def _engine(engine_seed: int = 37, **config: Any) -> Tetris:
    return Tetris(config=config, seed=engine_seed, seats=[{"seat": 0}, {"seat": 1}])


def _force_piece(engine: Tetris, seat: int, piece: str) -> None:
    index = engine.piece_indices[seat]
    engine._ensure_piece(index)
    engine._piece_sequence[index] = piece


def _fill_for_vertical_i_clear(engine: Tetris, seat: int, line_count: int) -> None:
    columns = int(engine.config["columns"])
    rows = int(engine.config["rows"])
    for row in range(rows - line_count, rows):
        engine.boards[seat][row] = [None] + [GARBAGE_CELL] * (columns - 1)


def _vertical_i_action() -> dict[str, int | bool]:
    return {"rotation": 1, "column": 0, "drop": True}


def test_defaults_are_two_player_bounded_and_fair() -> None:
    engine = _engine()

    assert engine.config["columns"] == 10
    assert engine.config["rows"] == 20
    assert len(engine.boards) == 2
    assert engine.boards[0] == engine.boards[1]
    assert engine._piece(0) == engine._piece(1)
    assert engine._piece(0, 1) == engine._piece(1, 1)
    assert engine.get_scores()["players"][0]["score"] == 0


@pytest.mark.parametrize(
    ("config", "match"),
    [
        ({"columns": 5}, "greater than or equal"),
        ({"columns": 17}, "less than or equal"),
        ({"rows": 11}, "greater than or equal"),
        ({"rows": 41}, "less than or equal"),
        ({"tick_rate": 0}, "greater than or equal"),
        ({"tick_rate": 21}, "less than or equal"),
        ({"max_duration_seconds": 29}, "greater than or equal"),
        ({"max_duration_seconds": 3_601}, "less than or equal"),
        ({"max_pieces_per_player": 0}, "greater than or equal"),
        ({"max_pieces_per_player": 2_001}, "less than or equal"),
        ({"tick_rate": 20, "max_duration_seconds": 1_001}, "must not exceed"),
        ({"columns": True}, "valid integer"),
        ({"rows": 20.0}, "valid integer"),
        ({"seed": math.inf}, "valid integer"),
        ({"unknown_rule": 1}, "Extra inputs are not permitted"),
    ],
)
def test_config_is_strict_and_resource_bounded(config: dict[str, Any], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        _engine(**config)


def test_base_contract_rejects_bad_seed_and_seats() -> None:
    with pytest.raises(ValueError, match="seed"):
        Tetris(config={}, seed=-1, seats=[{"seat": 0}, {"seat": 1}])
    with pytest.raises(ValueError, match="expected 2 seats"):
        Tetris(config={}, seed=1, seats=[{"seat": 0}])
    with pytest.raises(ValueError, match="ordered"):
        Tetris(config={}, seed=1, seats=[{"seat": 1}, {"seat": 0}])


def test_each_seven_bag_contains_every_tetromino_once() -> None:
    engine = _engine()
    engine._ensure_piece(20)

    assert set(engine._piece_sequence[0:7]) == set(PIECE_TYPES)
    assert set(engine._piece_sequence[7:14]) == set(PIECE_TYPES)
    assert set(engine._piece_sequence[14:21]) == set(PIECE_TYPES)


def test_seats_consume_the_same_nth_piece_even_at_different_rates() -> None:
    engine = _engine()
    sequence = engine._piece_sequence.copy()

    engine.step({0: engine.get_legal_actions(0)[0]})
    engine.step({0: engine.get_legal_actions(0)[0], 1: engine.get_legal_actions(1)[0]})

    assert engine.piece_indices == [2, 1]
    assert engine._piece(0) == sequence[2]
    assert engine._piece(1) == sequence[1]


@pytest.mark.parametrize("piece", PIECE_TYPES)
@pytest.mark.parametrize("rotation", range(4))
@pytest.mark.parametrize("edge", ["left", "right"])
def test_every_piece_rotation_locks_at_both_board_edges(
    piece: str, rotation: int, edge: str
) -> None:
    engine = _engine()
    _force_piece(engine, 0, piece)
    cells = SHAPES[piece][rotation]
    width = max(column for _, column in cells) + 1
    column = 0 if edge == "left" else int(engine.config["columns"]) - width

    engine.step({0: {"rotation": rotation, "column": column, "drop": True}})

    assert engine.piece_indices[0] == 1
    assert sum(cell == piece for row in engine.boards[0] for cell in row) == 4
    assert engine.last_move is not None
    assert engine.last_move["placements"][0]["column"] == column


def test_compact_kick_tries_exact_then_left_then_right() -> None:
    engine = _engine()
    _force_piece(engine, 0, "I")
    engine.boards[0][0][0] = GARBAGE_CELL

    engine.step({0: {"rotation": 0, "column": 0, "drop": True}})

    assert engine.last_move is not None
    assert engine.last_move["placements"][0]["requested_column"] == 0
    assert engine.last_move["placements"][0]["column"] == 1


@pytest.mark.parametrize(
    ("cleared", "score", "attack"),
    [
        (1, CLEAR_POINTS[1], ATTACK_ROWS[1]),
        (2, CLEAR_POINTS[2], ATTACK_ROWS[2]),
        (3, CLEAR_POINTS[3], ATTACK_ROWS[3]),
        (4, CLEAR_POINTS[4], ATTACK_ROWS[4]),
    ],
)
def test_line_clear_scoring_and_attack_table(cleared: int, score: int, attack: int) -> None:
    engine = _engine()
    _force_piece(engine, 0, "I")
    _fill_for_vertical_i_clear(engine, 0, cleared)

    engine.step({0: _vertical_i_action()})

    assert engine.lines[0] == cleared
    assert engine.scores[0] == score
    assert engine.attacks[0] == attack
    assert engine.garbage_received[1] == attack


def test_equal_simultaneous_attacks_cancel_completely() -> None:
    engine = _engine()
    for seat in (0, 1):
        _force_piece(engine, seat, "I")
        _fill_for_vertical_i_clear(engine, seat, 2)

    engine.step({0: _vertical_i_action(), 1: _vertical_i_action()})

    assert engine.last_move is not None
    assert engine.last_move["cancelled"] == 1
    assert engine.last_move["garbage"] == [0, 0]
    assert engine.attacks == [0, 0]
    assert engine.garbage_received == [0, 0]


def test_unequal_simultaneous_attacks_deliver_only_the_net_rows() -> None:
    engine = _engine()
    for seat in (0, 1):
        _force_piece(engine, seat, "I")
    _fill_for_vertical_i_clear(engine, 0, 4)
    _fill_for_vertical_i_clear(engine, 1, 2)

    engine.step({0: _vertical_i_action(), 1: _vertical_i_action()})

    assert engine.last_move is not None
    assert engine.last_move["cancelled"] == 1
    assert engine.last_move["garbage"] == [0, 3]
    assert engine.attacks == [3, 0]
    assert engine.garbage_received == [0, 3]
    for row in engine.boards[1][-3:]:
        assert row.count(None) == 1
        assert row.count(GARBAGE_CELL) == int(engine.config["columns"]) - 1


def test_garbage_holes_are_deterministic_and_seat_fair() -> None:
    first = _engine(engine_seed=99)
    assert not first._add_garbage(0, 8)
    # Receipt timing and unrelated empty ticks do not select different holes.
    for _ in range(7):
        first.step({})
    assert not first._add_garbage(1, 8)
    seat_zero_rows = copy.deepcopy(first.boards[0][-8:])

    second = _engine(engine_seed=99)
    assert not second._add_garbage(1, 8)

    assert first.boards[0][-8:] == first.boards[1][-8:]
    assert second.boards[1][-8:] == seat_zero_rows


def test_completely_full_boards_are_an_immediate_simultaneous_top_out() -> None:
    engine = _engine()
    for seat in (0, 1):
        engine.boards[seat] = [
            [GARBAGE_CELL] * int(engine.config["columns"])
            for _ in range(int(engine.config["rows"]))
        ]

    engine.step(
        {
            0: {"rotation": 0, "column": 0, "drop": True},
            1: {"rotation": 0, "column": 0, "drop": True},
        }
    )

    assert engine.is_terminal()
    assert engine.top_out == [True, True]
    assert engine.get_winner() is None
    assert engine.piece_indices == [0, 0]


def test_garbage_overflow_awards_the_attacker() -> None:
    engine = _engine()
    _force_piece(engine, 0, "I")
    _fill_for_vertical_i_clear(engine, 0, 4)
    # One occupied top cell still leaves legal spawn columns, but any incoming
    # garbage row shifts it out of the visible board and causes overflow.
    engine.boards[1][0][0] = GARBAGE_CELL

    engine.step({0: _vertical_i_action()})

    assert engine.is_terminal()
    assert engine.top_out == [False, True]
    assert engine.get_winner() == [0]
    assert "top-out" in engine.summary()


def test_one_blocked_spawn_loses_even_when_no_action_is_submitted() -> None:
    engine = _engine()
    engine.boards[0][0] = [GARBAGE_CELL] * int(engine.config["columns"])

    engine.step({})

    assert engine.top_out == [True, False]
    assert engine.get_winner() == [1]
    assert engine.piece_indices == [0, 0]


def test_simultaneous_top_out_is_a_draw() -> None:
    engine = _engine()
    for seat in (0, 1):
        engine.boards[seat][0] = [GARBAGE_CELL] * int(engine.config["columns"])

    engine.step({})

    assert engine.is_terminal()
    assert engine.top_out == [True, True]
    assert engine.get_winner() is None
    assert "draw" in engine.summary()


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        True,
        7,
        math.nan,
        math.inf,
        "drop",
        [0, 0],
        {},
        {"rotation": 0, "column": 0},
        {"rotation": True, "column": 0, "drop": True},
        {"rotation": 0.0, "column": 0, "drop": True},
        {"rotation": 4, "column": 0, "drop": True},
        {"rotation": 0, "column": True, "drop": True},
        {"rotation": 0, "column": math.nan, "drop": True},
        {"rotation": 0, "column": math.inf, "drop": True},
        {"rotation": 0, "column": 10**100, "drop": True},
        {"rotation": 0, "column": 0, "drop": False},
        {"rotation": 0, "column": 0, "drop": 1},
        {"rotation": 0, "column": 0, "drop": True, "extra": "ignored?"},
    ],
)
def test_malformed_actions_are_safe_noops(garbage: Any) -> None:
    engine = _engine()
    before = copy.deepcopy(engine.boards[0])

    engine.step({0: garbage})

    assert engine.boards[0] == before
    assert engine.piece_indices[0] == 0
    assert engine.tick == 1
    assert engine.last_move is not None
    assert engine.last_move["placements"][0] is None


def test_malformed_moves_envelope_is_treated_as_both_missing() -> None:
    engine = _engine()

    engine.step(cast(dict[int, Any], None))

    assert engine.piece_indices == [0, 0]
    assert engine.tick == 1


def test_legal_actions_are_exhaustive_accepted_atomic_placements() -> None:
    engine = _engine()
    legal = engine.get_legal_actions(0)

    assert legal
    assert len(legal) <= 4 * int(engine.config["columns"])
    assert all(set(action) == {"rotation", "column", "drop"} for action in legal)
    assert all(action["drop"] is True for action in legal)
    assert engine.get_legal_actions(-1) == []

    for action in legal:
        probe = _engine(engine_seed=37)
        probe.step({0: action})
        assert probe.piece_indices[0] == 1


def test_piece_cap_ends_after_equal_opportunity_and_uses_score() -> None:
    engine = _engine(max_pieces_per_player=1)
    _force_piece(engine, 0, "I")
    _force_piece(engine, 1, "I")
    _fill_for_vertical_i_clear(engine, 0, 1)

    engine.step({0: _vertical_i_action(), 1: _vertical_i_action()})

    assert engine.is_terminal()
    assert engine.piece_indices == [1, 1]
    assert engine.get_winner() == [0]
    assert "score limit" in engine.summary()


def test_equal_scores_at_piece_cap_draw() -> None:
    engine = _engine(max_pieces_per_player=1)
    actions = {seat: engine.get_legal_actions(seat)[0] for seat in (0, 1)}

    engine.step(actions)

    assert engine.piece_indices == [1, 1]
    assert engine.get_winner() is None


def test_tick_limit_uses_objective_score_without_extra_piece() -> None:
    engine = _engine(tick_rate=1, max_duration_seconds=30)
    engine.scores = [300, 100]

    for _ in range(30):
        engine.step({})

    assert engine.is_terminal()
    assert engine.tick == 30
    assert engine.piece_indices == [0, 0]
    assert engine.get_winner() == [0]


def test_terminal_step_is_strictly_immutable() -> None:
    engine = _engine(max_pieces_per_player=1)
    actions = {seat: engine.get_legal_actions(seat)[0] for seat in (0, 1)}
    engine.step(actions)
    before = (
        engine.get_render_data(),
        engine.observe(),
        engine.get_scores(),
        engine._piece_rng.getstate(),
        engine._garbage_rng.getstate(),
    )

    engine.step({0: {"rotation": 3, "column": 9, "drop": True}})

    assert (
        engine.get_render_data(),
        engine.observe(),
        engine.get_scores(),
        engine._piece_rng.getstate(),
        engine._garbage_rng.getstate(),
    ) == before


def test_same_seed_and_actions_have_identical_replay_frames() -> None:
    def play() -> list[dict[str, Any]]:
        engine = _engine(engine_seed=123)
        frames = [engine.get_render_data()]
        for tick in range(25):
            moves: dict[int, Any] = {}
            for seat in (0, 1):
                legal = engine.get_legal_actions(seat)
                if legal and (tick + seat) % 3 != 0:
                    moves[seat] = legal[(tick * 7 + seat) % len(legal)]
            engine.step(moves)
            frames.append(engine.get_render_data())
            if engine.is_terminal():
                break
        return frames

    assert play() == play()


def test_reset_restores_initial_state_and_replay_identity() -> None:
    engine = _engine(engine_seed=54)
    initial = engine.get_render_data()
    actions = {seat: engine.get_legal_actions(seat)[-1] for seat in (0, 1)}
    engine.step(actions)
    first_frame = engine.get_render_data()

    engine.reset()
    assert engine.get_render_data() == initial
    engine.step(actions)
    assert engine.get_render_data() == first_frame


def test_observation_render_scores_and_legal_actions_are_defensive_copies() -> None:
    engine = _engine()
    engine.step({0: engine.get_legal_actions(0)[0]})
    observation = engine.observe()
    render = engine.get_render_data()
    scores = engine.get_scores()

    observation["state"]["boards"][0]["board"][0][0] = "CORRUPT"
    observation["state"]["boards"][0]["next"].clear()
    observation["legal_actions"][0][0]["column"] = -99
    observation["last_move"]["placements"][0]["piece"] = "CORRUPT"
    render["boards"][0]["board"][0][0] = "CORRUPT"
    render["boards"][0]["next"].clear()
    scores["players"][0]["score"] = 999_999

    assert all(cell != "CORRUPT" for row in engine.boards[0] for cell in row)
    assert engine._piece(0, 1) in PIECE_TYPES
    assert engine.get_legal_actions(0)[0]["column"] >= 0
    assert engine.last_move is not None
    assert engine.last_move["placements"][0]["piece"] in PIECE_TYPES
    assert engine.scores[0] != 999_999


def test_maximum_board_keeps_state_and_work_bounded() -> None:
    engine = _engine(columns=16, rows=40, max_pieces_per_player=2_000)

    for _ in range(100):
        engine.step({})

    assert engine.tick == 100
    assert len(engine.boards) == 2
    assert all(len(board) == 40 for board in engine.boards)
    assert all(len(row) == 16 for board in engine.boards for row in board)
    assert len(engine.get_legal_actions(0)) <= 64
    assert len(engine._piece_sequence) <= 7
    assert len(engine._garbage_holes) == 0
