"""Adversarial rules tests for WCDF English draughts."""

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.engine.base import IllegalMove
from app.engine.games.checkers import Checkers, _Piece

SEATS = [{"seat": 0}, {"seat": 1}]


def _checkers(**config: Any) -> Checkers:
    config.setdefault("time_control", {"enabled": False})
    return Checkers(config=config, seed=17, seats=list(SEATS))


def _position(
    engine: Checkers,
    pieces: dict[str, tuple[int, bool]],
    *,
    turn: int = 0,
    no_progress: int = 0,
) -> None:
    engine.board = {
        (ord(square[0]) - 97, int(square[1]) - 1): _Piece(seat, king)
        for square, (seat, king) in pieces.items()
    }
    engine.turn = turn
    engine.move_count = 0
    engine.no_progress_halfmoves = no_progress
    engine.forced_from = None
    engine._pending_captures = set()
    engine._turn_path = []
    engine.last_move = None
    engine._terminal = False
    engine._winner = None
    engine._end_reason = None
    engine._initialize_clock()


def _moves(engine: Checkers) -> list[dict[str, str]]:
    actions = engine.get_legal_actions(engine.current_seat())
    return [action for action in actions if "from" in action]


def test_initial_position_and_action_contract() -> None:
    engine = _checkers()
    scores = engine.get_scores()
    assert scores["pieces"] == [12, 12]
    assert scores["kings"] == [0, 0]
    assert engine.current_seat() == 0
    assert len(_moves(engine)) == 7
    assert {"from": "a3", "to": "b4"} in _moves(engine)
    assert engine.get_legal_actions(1) == []
    assert engine.get_legal_actions(True) == []


def test_global_mandatory_capture_suppresses_all_quiet_moves() -> None:
    engine = _checkers()
    _position(engine, {"a3": (0, False), "c3": (0, False), "d4": (1, False)})
    assert _moves(engine) == [{"from": "c3", "to": "e5"}]

    with pytest.raises(IllegalMove) as exc_info:
        engine.apply_action({"from": "a3", "to": "b4"})
    assert exc_info.value.code == "capture_required"
    assert engine.current_seat() == 0


def test_capture_choice_does_not_impose_international_max_capture_rule() -> None:
    engine = _checkers()
    _position(
        engine,
        {
            "c3": (0, False),
            "b4": (1, False),
            "d4": (1, False),
            "f6": (1, False),
        },
    )
    assert _moves(engine) == [
        {"from": "c3", "to": "a5"},
        {"from": "c3", "to": "e5"},
    ]
    engine.apply_action({"from": "c3", "to": "a5"})
    assert engine.current_seat() == 1


def test_multi_jump_retains_turn_and_only_advertises_continuations() -> None:
    engine = _checkers()
    _position(engine, {"c3": (0, False), "d4": (1, False), "f6": (1, False)})

    engine.apply_action({"from": "c3", "to": "e5"})
    assert engine.current_seat() == 0
    assert engine.move_count == 1
    assert _moves(engine) == [{"from": "e5", "to": "g7"}]
    assert engine.get_render_data()["forced_from"] == "e5"
    assert engine.get_scores()["pieces"] == [1, 1]

    snapshot = deepcopy(engine.get_render_data())
    with pytest.raises(IllegalMove) as exc_info:
        engine.apply_action({"from": "e5", "to": "d6"})
    assert exc_info.value.code == "must_continue_capture"
    assert engine.get_render_data() == snapshot

    engine.apply_action({"from": "e5", "to": "g7"})
    assert engine.is_terminal()
    assert engine.get_winner() == [0]
    assert engine.move_count == 2


def test_captured_pieces_block_and_cannot_be_jumped_twice_in_a_sequence() -> None:
    engine = _checkers()
    _position(
        engine,
        {
            "c3": (0, True),
            "d4": (1, False),
            "d6": (1, False),
            "b6": (1, False),
            "b4": (1, False),
            "h8": (1, True),
        },
    )
    for action in (
        {"from": "c3", "to": "e5"},
        {"from": "e5", "to": "c7"},
        {"from": "c7", "to": "a5"},
        {"from": "a5", "to": "c3"},
    ):
        engine.apply_action(action)

    assert engine.current_seat() == 1
    assert engine.move_count == 4
    assert engine.get_scores()["pieces"] == [1, 1]
    assert {piece["square"] for piece in engine.get_render_data()["pieces"]} == {"c3", "h8"}


def test_men_move_and_capture_forward_only() -> None:
    engine = _checkers()
    _position(engine, {"c5": (0, False), "b4": (1, False)})
    assert {"from": "c5", "to": "a3"} not in _moves(engine)
    assert _moves(engine) == [
        {"from": "c5", "to": "b6"},
        {"from": "c5", "to": "d6"},
    ]

    _position(engine, {"c5": (0, False), "b4": (1, False), "d6": (1, False)})
    assert _moves(engine) == [{"from": "c5", "to": "e7"}]


def test_kings_are_short_range_and_move_and_capture_both_directions() -> None:
    engine = _checkers()
    _position(engine, {"c3": (0, True), "h8": (1, True)})
    assert set((move["from"], move["to"]) for move in _moves(engine)) == {
        ("c3", "b2"),
        ("c3", "d2"),
        ("c3", "b4"),
        ("c3", "d4"),
    }
    with pytest.raises(IllegalMove):
        engine.apply_action({"from": "c3", "to": "f6"})

    _position(engine, {"c3": (0, True), "b2": (1, False), "h8": (1, True)})
    assert _moves(engine) == [{"from": "c3", "to": "a1"}]


def test_crowning_ends_capture_turn_before_new_king_can_jump_backward() -> None:
    engine = _checkers()
    _position(engine, {"b6": (0, False), "c7": (1, False), "e7": (1, False)})
    engine.apply_action({"from": "b6", "to": "d8"})

    piece = next(piece for piece in engine.get_render_data()["pieces"] if piece["square"] == "d8")
    assert piece["king"] is True
    assert engine.current_seat() == 1
    assert engine.move_count == 1
    assert engine.last_move["promoted"] is True
    assert {item["square"] for item in engine.get_render_data()["pieces"]} == {"d8", "e7"}


def test_player_with_no_pieces_or_no_legal_move_loses() -> None:
    engine = _checkers()
    _position(engine, {"c3": (0, False), "d4": (1, False)})
    engine.apply_action({"from": "c3", "to": "e5"})
    assert engine.get_winner() == [0]

    engine = _checkers()
    _position(engine, {"c3": (0, False), "a1": (1, False)})
    engine.apply_action({"from": "c3", "to": "b4"})
    assert engine.is_terminal()
    assert engine.get_winner() == [0]
    assert "no legal moves" in engine.summary()


def test_no_progress_draw_increments_once_per_turn_and_resets_on_progress() -> None:
    engine = _checkers(no_progress_halfmoves=2)
    _position(engine, {"c3": (0, True), "h8": (1, True)})
    engine.apply_action({"from": "c3", "to": "b4"})
    assert engine.no_progress_halfmoves == 1
    engine.apply_action({"from": "h8", "to": "g7"})
    assert engine.is_terminal()
    assert engine.get_winner() is None
    assert "draw" in engine.summary()

    engine = _checkers(no_progress_halfmoves=4)
    _position(engine, {"a3": (0, False), "h8": (1, True)}, no_progress=3)
    engine.apply_action({"from": "a3", "to": "b4"})
    assert engine.no_progress_halfmoves == 0

    engine = _checkers(no_progress_halfmoves=4)
    _position(
        engine,
        {"c3": (0, True), "d4": (1, False), "h8": (1, True)},
        no_progress=3,
    )
    engine.apply_action({"from": "c3", "to": "e5"})
    assert not engine.is_terminal()
    assert engine.no_progress_halfmoves == 0


def test_multi_jump_clock_and_increment_are_committed_once_per_completed_turn() -> None:
    engine = Checkers(
        config={"time_control": {"enabled": True, "base_sec": 60, "increment_sec": 5}},
        seed=17,
        seats=list(SEATS),
    )
    _position(engine, {"c3": (0, False), "d4": (1, False), "f6": (1, False)})
    before = engine._clock_remaining_ms[0]
    engine.apply_action({"from": "c3", "to": "e5"})
    assert engine._active_clock_seat == 0
    assert engine.move_count == 1
    assert engine._clock_remaining_ms[0] == before

    engine.apply_action({"from": "e5", "to": "g7"})
    assert engine.move_count == 2
    assert engine._clock_remaining_ms[0] >= before + 4_900


@pytest.mark.parametrize(
    ("action", "code"),
    [
        (None, "invalid_action"),
        ("a3b4", "invalid_action"),
        ([], "invalid_action"),
        ({}, "invalid_action"),
        ({"from": True, "to": "b4"}, "invalid_square"),
        ({"from": "a3", "to": 4}, "invalid_square"),
        ({"from": "A3", "to": "b4"}, "invalid_square"),
        ({"from": "a3", "to": "b4", "extra": 1}, "invalid_action"),
        ({"resign": False}, "invalid_action"),
        ({"resign": True, "from": "a3", "to": "b4"}, "invalid_action"),
    ],
)
def test_malformed_actions_are_rejected_without_mutation(action: Any, code: str) -> None:
    engine = _checkers()
    before = deepcopy(engine.get_render_data())
    with pytest.raises(IllegalMove) as exc_info:
        engine.apply_action(action)
    assert exc_info.value.code == code
    assert engine.get_render_data() == before


def test_resignation_and_terminal_state_are_immutable() -> None:
    engine = _checkers()
    engine.apply_action({"resign": True})
    assert engine.get_winner() == [1]
    assert "resignation" in engine.summary()
    terminal = deepcopy(engine.get_render_data())

    with pytest.raises(IllegalMove) as exc_info:
        engine.apply_action(None)
    assert exc_info.value.code == "game_over"
    assert engine.get_render_data() == terminal


def test_observation_and_render_snapshots_cannot_mutate_engine_history() -> None:
    engine = _checkers()
    engine.apply_action({"from": "a3", "to": "b4"})
    expected = deepcopy(engine.last_move)

    render = engine.get_render_data()
    render["last_move"]["from"] = "h8"
    render["last_move"]["sequence"].clear()
    observation = engine.observe()
    observation["last_move"]["to"] = "a1"
    observation["last_move"]["sequence"].append("a1")

    assert engine.last_move == expected


def test_config_is_strict_and_bounded() -> None:
    with pytest.raises(ValidationError):
        _checkers(no_progress_halfmoves=True)
    with pytest.raises(ValidationError):
        _checkers(no_progress_halfmoves=1)
    with pytest.raises(ValidationError):
        _checkers(unknown_option=True)
    with pytest.raises(ValueError, match="expected 2 seats"):
        Checkers(config={}, seed=1, seats=[{"seat": 0}])


def test_reset_and_independent_replay_are_equivalent() -> None:
    actions = [
        {"from": "a3", "to": "b4"},
        {"from": "d6", "to": "c5"},
        {"from": "b4", "to": "d6"},
    ]
    first = _checkers()
    for action in actions:
        first.apply_action(action)
    expected = deepcopy(first.get_render_data())

    replay = _checkers()
    for action in actions:
        replay.apply_action(action)
    assert replay.get_render_data() == expected
    assert replay.get_scores() == first.get_scores()

    first.reset()
    assert first.get_scores()["pieces"] == [12, 12]
    assert first.current_seat() == 0
    for action in actions:
        first.apply_action(action)
    assert first.get_render_data() == expected
