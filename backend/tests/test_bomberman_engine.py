"""Adversarial contract tests for deterministic Bomberman Duel."""

from __future__ import annotations

import copy
import math
import time
from typing import Any, cast

import pytest
from pydantic import ValidationError

from app.engine.games.bomberman import (
    MAX_DIMENSION,
    MIN_DIMENSION,
    Bomb,
    Bomberman,
)


def _engine(engine_seed: int = 37, **config: Any) -> Bomberman:
    return Bomberman(config=config, seed=engine_seed, seats=[{"seat": 0}, {"seat": 1}])


def _empty(engine: Bomberman) -> None:
    engine.crates.clear()
    engine._hidden_powerups.clear()
    engine.powerups.clear()


def _add_bomb(
    engine: Bomberman,
    position: tuple[int, int],
    *,
    owner: int,
    fuse: int,
    blast_range: int = 3,
) -> None:
    engine.bombs[position] = Bomb(owner=owner, fuse=fuse, blast_range=blast_range)
    engine.active_bombs[owner] += 1


def test_default_board_is_bounded_symmetric_and_has_safe_spawn_exits() -> None:
    engine = _engine()
    width = engine.config["width"]
    height = engine.config["height"]
    assert MIN_DIMENSION <= width <= MAX_DIMENSION
    assert MIN_DIMENSION <= height <= MAX_DIMENSION
    assert width % 2 == height % 2 == 1
    assert engine.positions == [(1, 1), (width - 2, height - 2)]

    for cell in engine.solid_walls:
        assert engine._mirror(cell) in engine.solid_walls
    for cell in engine.crates:
        assert engine._mirror(cell) in engine.crates
    for cell, kind in engine._hidden_powerups.items():
        assert engine._hidden_powerups[engine._mirror(cell)] == kind

    safe_cells = {
        (1, 1),
        (2, 1),
        (1, 2),
        (width - 2, height - 2),
        (width - 3, height - 2),
        (width - 2, height - 3),
    }
    assert not (safe_cells & engine.crates)
    assert engine.positions[0] not in engine.solid_walls
    assert engine.positions[1] not in engine.solid_walls


@pytest.mark.parametrize(
    "config",
    [
        {"width": MIN_DIMENSION - 1},
        {"width": MAX_DIMENSION + 1},
        {"width": 10},
        {"height": 14},
        {"height": True},
        {"tick_rate": 1},
        {"tick_rate": 31},
        {"max_ticks": 0},
        {"max_ticks": 10_001},
        {"bomb_fuse_ticks": 1},
        {"flame_ticks": 31},
        {"starting_capacity": 9},
        {"starting_range": 9},
        {"starting_capacity": 5, "max_capacity": 4},
        {"starting_range": 6, "max_blast_range": 5},
        {"crate_density": -0.01},
        {"crate_density": 0.86},
        {"powerup_chance": math.nan},
        {"powerup_chance": math.inf},
        {"tick_rate": 8.0},
        {"unknown_rule": 1},
    ],
)
def test_config_is_strict_and_resource_bounded(config: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _engine(**config)


def test_base_contract_rejects_bad_seed_and_seats() -> None:
    with pytest.raises(ValueError, match="seed"):
        Bomberman(config={}, seed=-1, seats=[{"seat": 0}, {"seat": 1}])
    with pytest.raises(ValueError, match="expected 2 seats"):
        Bomberman(config={}, seed=1, seats=[{"seat": 0}])
    with pytest.raises(ValueError, match="ordered"):
        Bomberman(config={}, seed=1, seats=[{"seat": 1}, {"seat": 0}])


@pytest.mark.parametrize(
    "garbage",
    [
        None,
        True,
        17,
        math.nan,
        math.inf,
        "left",
        ["left"],
        {},
        {"move": "left"},
        {"bomb": False},
        {"move": "teleport", "bomb": False},
        {"move": math.nan, "bomb": False},
        {"move": ["left"], "bomb": False},
        {"move": "left", "bomb": 1},
        {"move": "left", "bomb": False, "extra": True},
    ],
)
def test_malformed_actions_are_exact_safe_noops(garbage: Any) -> None:
    engine = _engine(crate_density=0.0)
    starts = engine.positions.copy()
    engine.step({0: garbage})
    assert engine.positions == starts
    assert not engine.bombs
    assert engine.last_move is not None
    assert engine.last_move["actions"] == [
        {"move": "noop", "bomb": False},
        {"move": "noop", "bomb": False},
    ]


def test_malformed_moves_envelope_is_both_noop() -> None:
    engine = _engine(crate_density=0.0)
    starts = engine.positions.copy()
    engine.step(cast(dict[int, Any], None))
    assert engine.positions == starts


def test_placing_bomb_then_leaving_works_and_fuse_is_not_aged_immediately() -> None:
    engine = _engine(crate_density=0.0, bomb_fuse_ticks=3)
    origin = engine.positions[0]
    engine.step({0: {"move": "right", "bomb": True}})

    assert engine.positions[0] == (origin[0] + 1, origin[1])
    assert engine.bombs[origin] == Bomb(owner=0, fuse=3, blast_range=2)
    assert engine.active_bombs == [1, 0]
    assert engine.last_move is not None
    assert engine.last_move["placed"] == [{"seat": 0, "at": [*origin]}]

    engine.step({0: {"move": "noop", "bomb": False}})
    assert engine.bombs[origin].fuse == 2


def test_wall_crate_and_bomb_cells_block_entry() -> None:
    engine = _engine(crate_density=0.0)
    engine.positions = [(1, 1), (7, 7)]

    engine.step({0: {"move": "left", "bomb": False}})
    assert engine.positions[0] == (1, 1)
    assert engine.last_move is not None and engine.last_move["movement"][0]["blocked"]

    engine.crates.add((2, 1))
    engine.step({0: {"move": "right", "bomb": False}})
    assert engine.positions[0] == (1, 1)

    engine.crates.clear()
    _add_bomb(engine, (2, 1), owner=1, fuse=50)
    engine.step({0: {"move": "right", "bomb": False}})
    assert engine.positions[0] == (1, 1)


def test_duplicate_bomb_occupancy_and_capacity_are_enforced() -> None:
    engine = _engine(crate_density=0.0, bomb_fuse_ticks=10)
    engine.step({0: {"move": "noop", "bomb": True}})
    first = engine.positions[0]
    assert set(engine.bombs) == {first}

    engine.step({0: {"move": "right", "bomb": True}})
    assert len(engine.bombs) == 1
    assert engine.active_bombs == [1, 0]
    assert not any(action["bomb"] for action in engine.get_legal_actions(0))


def test_same_cell_and_head_swap_movement_are_resolved_fairly() -> None:
    same = _engine(crate_density=0.0)
    same.positions = [(3, 3), (5, 3)]
    same.step(
        {
            0: {"move": "right", "bomb": False},
            1: {"move": "left", "bomb": False},
        }
    )
    assert same.positions == [(3, 3), (5, 3)]
    assert [entry["blocked"] for entry in same.last_move["movement"]] == [True, True]

    swap = _engine(crate_density=0.0)
    swap.positions = [(3, 3), (4, 3)]
    swap.step(
        {
            0: {"move": "right", "bomb": False},
            1: {"move": "left", "bomb": False},
        }
    )
    assert swap.positions == [(3, 3), (4, 3)]


def test_mover_cannot_enter_cell_of_player_whose_move_is_blocked() -> None:
    engine = _engine(crate_density=0.0)
    engine.positions = [(3, 3), (4, 3)]
    engine.crates.add((5, 3))
    engine.step(
        {
            0: {"move": "right", "bomb": False},
            1: {"move": "right", "bomb": False},
        }
    )
    assert engine.positions == [(3, 3), (4, 3)]


def test_solid_walls_stop_blast_and_crates_are_hit_but_stop_ray() -> None:
    engine = _engine(crate_density=0.0, flame_ticks=3)
    engine.positions = [(7, 7), (9, 7)]
    engine.crates = {(3, 1)}
    _add_bomb(engine, (1, 1), owner=0, fuse=1, blast_range=5)

    engine.step({})

    assert (3, 1) not in engine.crates
    assert (1, 1) in engine.flames
    assert (2, 1) in engine.flames
    assert (3, 1) in engine.flames
    assert (4, 1) not in engine.flames
    assert (0, 1) not in engine.flames
    assert engine.active_bombs == [0, 0]


def test_internal_pillar_stops_blast_before_cell_beyond_it() -> None:
    engine = _engine(crate_density=0.0)
    engine.positions = [(7, 7), (9, 7)]
    _add_bomb(engine, (1, 2), owner=0, fuse=1, blast_range=4)
    engine.step({})
    assert (2, 2) in engine.solid_walls
    assert (2, 2) not in engine.flames
    assert (3, 2) not in engine.flames


def test_chain_reactions_are_immediate_and_release_each_owners_capacity() -> None:
    engine = _engine(crate_density=0.0)
    engine.positions = [(1, 7), (11, 9)]
    _add_bomb(engine, (3, 3), owner=0, fuse=1, blast_range=3)
    _add_bomb(engine, (5, 3), owner=1, fuse=99, blast_range=2)

    engine.step({})

    assert not engine.bombs
    assert engine.active_bombs == [0, 0]
    assert engine.last_move is not None
    assert [event["owner"] for event in engine.last_move["explosions"]] == [0, 1]


def test_newly_placed_bomb_can_be_chain_triggered_on_placement_tick() -> None:
    engine = _engine(crate_density=0.0, starting_range=4)
    engine.positions = [(3, 3), (5, 3)]
    _add_bomb(engine, (1, 3), owner=0, fuse=1, blast_range=5)
    engine.step({1: {"move": "down", "bomb": True}})
    assert (5, 3) not in engine.bombs
    assert engine.active_bombs == [0, 0]
    assert len(engine.last_move["explosions"]) == 2


def test_one_death_awards_survivor_and_simultaneous_death_draws() -> None:
    winner = _engine(crate_density=0.0)
    winner.positions = [(3, 1), (9, 7)]
    _add_bomb(winner, (3, 3), owner=1, fuse=1, blast_range=3)
    winner.step({})
    assert winner.is_terminal()
    assert winner.alive == [False, True]
    assert winner.get_winner() == [1]

    draw = _engine(crate_density=0.0)
    draw.positions = [(3, 1), (3, 5)]
    _add_bomb(draw, (3, 3), owner=0, fuse=1, blast_range=3)
    draw.step({})
    assert draw.is_terminal()
    assert draw.alive == [False, False]
    assert draw.get_winner() is None
    assert "simultaneous knockout" in draw.summary()


def test_flames_have_exact_lifetime_and_remain_hazardous() -> None:
    engine = _engine(crate_density=0.0, flame_ticks=2)
    engine.positions = [(7, 7), (9, 7)]
    _add_bomb(engine, (1, 1), owner=0, fuse=1, blast_range=1)
    engine.step({})
    assert engine.flames[(1, 1)] == 2
    engine.step({})
    assert engine.flames[(1, 1)] == 1
    engine.step({})
    assert (1, 1) not in engine.flames


def test_destroyed_crate_reveals_seeded_powerup_after_blast() -> None:
    engine = _engine(crate_density=0.0, flame_ticks=2)
    engine.positions = [(7, 7), (9, 7)]
    engine.crates = {(3, 1)}
    engine._hidden_powerups = {(3, 1): "capacity"}
    _add_bomb(engine, (1, 1), owner=0, fuse=1, blast_range=3)
    engine.step({})
    assert engine.powerups == {(3, 1): "capacity"}
    assert (3, 1) in engine.flames


@pytest.mark.parametrize(
    ("kind", "attribute", "maximum"),
    [("capacity", "capacities", "max_capacity"), ("range", "blast_ranges", "max_blast_range")],
)
def test_powerup_collection_updates_stats_but_respects_cap(
    kind: str, attribute: str, maximum: str
) -> None:
    engine = _engine(crate_density=0.0)
    engine.positions[0] = (1, 1)
    engine.powerups[(2, 1)] = cast(Any, kind)
    stats = cast(list[int], getattr(engine, attribute))
    before = stats[0]
    engine.step({0: {"move": "right", "bomb": False}})
    assert stats[0] == before + 1
    assert engine.last_move["collected"] == [{"seat": 0, "at": [2, 1], "kind": kind}]

    stats[0] = int(engine.config[maximum])
    engine.powerups[(3, 1)] = cast(Any, kind)
    engine.step({0: {"move": "right", "bomb": False}})
    assert stats[0] == int(engine.config[maximum])


def test_previously_exposed_powerup_is_destroyed_by_later_blast() -> None:
    engine = _engine(crate_density=0.0)
    engine.positions = [(7, 7), (9, 7)]
    engine.powerups[(3, 1)] = "range"
    _add_bomb(engine, (1, 1), owner=0, fuse=1, blast_range=3)
    engine.step({})
    assert (3, 1) not in engine.powerups


def test_tick_cap_draw_and_elimination_takes_precedence() -> None:
    draw = _engine(crate_density=0.0, max_ticks=1)
    draw.step({})
    assert draw.is_terminal() and draw.get_winner() is None
    assert "tick-limit draw" in draw.summary()

    decisive = _engine(crate_density=0.0, max_ticks=1)
    decisive.positions = [(3, 1), (9, 7)]
    _add_bomb(decisive, (3, 3), owner=1, fuse=1, blast_range=3)
    decisive.step({})
    assert decisive.get_winner() == [1]


def test_terminal_step_is_strictly_immutable() -> None:
    engine = _engine(crate_density=0.0, max_ticks=1)
    engine.step({})
    before = (
        engine.get_render_data(),
        engine.observe(),
        engine.get_winner(),
        engine.rng.getstate(),
    )
    engine.step({0: {"move": "right", "bomb": True}})
    assert (
        engine.get_render_data(),
        engine.observe(),
        engine.get_winner(),
        engine.rng.getstate(),
    ) == before


def test_reset_and_seeded_replay_are_deterministic() -> None:
    actions = [
        {0: {"move": "right", "bomb": True}, 1: {"move": "left", "bomb": True}},
        {0: {"move": "down", "bomb": False}, 1: {"move": "up", "bomb": False}},
        {0: {"move": "right", "bomb": False}, 1: {"move": "left", "bomb": False}},
    ]
    engine = _engine(engine_seed=123)
    initial = engine.get_render_data()
    first_frames = []
    for action in actions:
        engine.step(action)
        first_frames.append(engine.get_render_data())

    engine.reset()
    assert engine.get_render_data() == initial
    second_frames = []
    for action in actions:
        engine.step(action)
        second_frames.append(engine.get_render_data())
    assert second_frames == first_frames
    assert _engine(engine_seed=123).get_render_data() == initial


def test_observation_render_scores_and_last_move_are_defensive_copies() -> None:
    engine = _engine(crate_density=0.0)
    engine.step({0: {"move": "right", "bomb": True}})
    observation = engine.observe()
    render = engine.get_render_data()
    scores = engine.get_scores()

    observation["state"]["players"][0]["position"][0] = -99
    observation["state"]["bombs"].clear()
    observation["legal_actions"][0][0]["move"] = "teleport"
    observation["last_move"]["movement"][0]["to"][0] = -99
    render["players"][0]["position"][0] = -99
    render["solid_walls"].clear()
    scores["alive"][0] = False
    scores["capacity"][0] = 99

    assert engine.positions[0][0] >= 0
    assert engine.bombs
    assert engine.solid_walls
    assert engine.get_legal_actions(0)[0]["move"] == "up"
    assert engine.last_move["movement"][0]["to"][0] >= 0
    assert engine.alive[0]
    assert engine.capacities[0] != 99


def test_legal_actions_are_small_exact_and_capacity_aware() -> None:
    engine = _engine(crate_density=0.0)
    legal = engine.get_legal_actions(0)
    assert len(legal) == 10
    assert all(set(action) == {"move", "bomb"} for action in legal)
    assert {action["move"] for action in legal} == {"up", "down", "left", "right", "noop"}
    engine.step({0: {"move": "noop", "bomb": True}})
    assert len(engine.get_legal_actions(0)) == 5
    assert all(action["bomb"] is False for action in engine.get_legal_actions(0))
    assert engine.get_legal_actions(-1) == []


def test_maximum_board_and_busy_bomb_tick_remain_bounded() -> None:
    engine = _engine(
        width=MAX_DIMENSION,
        height=MAX_DIMENSION,
        crate_density=0.85,
        powerup_chance=1.0,
        starting_capacity=8,
        max_capacity=12,
        max_blast_range=12,
    )
    _empty(engine)
    engine.positions = [(1, 1), (MAX_DIMENSION - 2, MAX_DIMENSION - 2)]
    bomb_cells = [(x, 3) for x in range(1, 24, 2)][:8]
    for index, cell in enumerate(bomb_cells):
        _add_bomb(engine, cell, owner=index % 2, fuse=1 if index == 0 else 99, blast_range=12)

    started = time.perf_counter()
    engine.step({})
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25
    assert len(engine.get_render_data()["solid_walls"]) <= MAX_DIMENSION**2
    assert engine.active_bombs == [0, 0]
    assert all(count >= 0 for count in engine.active_bombs)


def test_active_bomb_counter_always_matches_authoritative_bomb_map() -> None:
    engine = _engine(crate_density=0.0, starting_capacity=3, bomb_fuse_ticks=3)
    actions = [
        {0: {"move": "right", "bomb": True}, 1: {"move": "left", "bomb": True}},
        {0: {"move": "right", "bomb": True}, 1: {"move": "left", "bomb": True}},
        {0: {"move": "down", "bomb": True}, 1: {"move": "up", "bomb": True}},
    ]
    for action in actions:
        engine.step(copy.deepcopy(action))
        expected = [sum(bomb.owner == seat for bomb in engine.bombs.values()) for seat in (0, 1)]
        assert engine.active_bombs == expected
        if engine.is_terminal():
            break
