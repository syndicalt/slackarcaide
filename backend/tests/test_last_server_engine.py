"""Adversarial state-machine and privacy coverage for Last Server."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from app.engine.base import IllegalMove
from app.engine.games.last_server import TEAM_SIZES, LastServer


def _seats(count: int = 6) -> list[dict[str, Any]]:
    return [
        {"seat": seat, "agent_id": f"agent-{seat}", "name": f"Agent {seat}"}
        for seat in range(count)
    ]


def _game(*, count: int = 6, seed: int = 17, **config: Any) -> LastServer:
    return LastServer(
        config={"players_required": count, **config},
        seed=seed,
        seats=_seats(count),
    )


def _team_with(game: LastServer, *required: int) -> list[int]:
    team = list(dict.fromkeys(required))
    team.extend(seat for seat in range(game.player_count) if seat not in team)
    return sorted(team[: game.team_size])


def _approve_team(game: LastServer, team: list[int]) -> None:
    game.apply_action({"team": team})
    while game.phase == "vote":
        game.apply_action({"vote": "approve"})


def _complete_mission(game: LastServer, *, sabotage: bool) -> None:
    corrupt = next(seat for seat, role in enumerate(game.roles) if role == "corrupted")
    _approve_team(game, _team_with(game, corrupt))
    while game.phase == "mission" and not game.is_terminal():
        seat = game.current_seat()
        action = "sabotage" if sabotage and game.roles[seat] == "corrupted" else "repair"
        game.apply_action({"mission": action})


@pytest.mark.parametrize(
    ("count", "corrupted"),
    [(5, 2), (6, 2), (7, 3)],
)
def test_role_assignment_is_seeded_bounded_and_reset_deterministic(
    count: int, corrupted: int
) -> None:
    game = _game(count=count)
    original = game.roles
    assert len(original) == count
    assert original.count("corrupted") == corrupted
    assert original.count("maintainer") == count - corrupted
    game.reset()
    assert game.roles == original
    assert game.phase == "proposal"
    assert game.current_seat() == 0
    assert TEAM_SIZES[count][0] == game.team_size


def test_config_and_seat_topology_are_strict() -> None:
    with pytest.raises(ValidationError):
        LastServer(config={"players_required": 4}, seed=1, seats=_seats(4))
    with pytest.raises(ValidationError):
        LastServer(config={"players_required": 6, "surprise": True}, seed=1, seats=_seats())
    with pytest.raises(ValueError, match="expected 6 seats"):
        LastServer(config={"players_required": 6}, seed=1, seats=_seats(5))
    with pytest.raises(ValueError, match="ordered and numbered"):
        LastServer(
            config={"players_required": 6},
            seed=1,
            seats=[*_seats(5), {"seat": 7, "agent_id": "bad"}],
        )


def test_public_state_never_exposes_live_roles_or_role_dependent_actions() -> None:
    game = _game()
    public = game.observe()
    assert "roles" not in public["state"]
    assert "your_role" not in public["state"]
    assert public["legal_actions"] == []

    corrupt = next(seat for seat, role in enumerate(game.roles) if role == "corrupted")
    maintainer = next(seat for seat, role in enumerate(game.roles) if role == "maintainer")
    corrupt_view = game.observe(corrupt)["state"]
    maintainer_view = game.observe(maintainer)["state"]
    assert corrupt_view["your_role"] == "corrupted"
    assert corrupt_view["known_corrupted_seats"] == game._faction_seats("corrupted")
    assert maintainer_view["your_role"] == "maintainer"
    assert maintainer_view["known_corrupted_seats"] == []


@pytest.mark.parametrize(
    "team",
    [
        [0],
        [0, 0],
        [0, True],
        [0, 99],
        [1, 0],
        "0,1",
    ],
)
def test_malformed_proposals_are_transactional(team: Any) -> None:
    game = _game()
    before = deepcopy(game.get_render_data())
    with pytest.raises(IllegalMove):
        game.apply_action({"team": team})
    assert game.get_render_data() == before
    assert game.move_count == 0


def test_proposal_actions_are_complete_canonical_and_bounded() -> None:
    game = _game()
    actions = game.get_legal_actions(0)
    teams = [action["team"] for action in actions if "team" in action]
    assert len(teams) == 15  # C(6, 2)
    assert teams == sorted(teams)
    assert all(team == sorted(set(team)) for team in teams)
    assert actions[-1] == {"resign": True}


def test_votes_remain_hidden_until_resolution_then_become_public() -> None:
    game = _game()
    team = _team_with(game)
    game.apply_action({"team": team})
    game.apply_action({"vote": "reject"})
    game.apply_action({"vote": "approve"})
    render = game.get_render_data()
    assert render["votes_submitted"] == 2
    assert "votes" not in render["last_move"]
    assert render["missions"] == []

    while game.phase == "vote":
        game.apply_action({"vote": "approve"})
    assert game.phase == "mission"
    assert game.last_move["approved"] is True
    assert game.last_move["votes"][0] == {"seat": 0, "vote": "reject"}


def test_rejected_proposals_rotate_coordinator_and_three_damage_server() -> None:
    game = _game()
    for attempt in range(3):
        game.apply_action({"team": _team_with(game)})
        while game.phase == "vote":
            game.apply_action({"vote": "reject"})
        if attempt < 2:
            assert game.phase == "proposal"
            assert game.rejected_proposals == attempt + 1

    assert game.sabotage_score == 1
    assert game.round_index == 1
    assert game.rejected_proposals == 0
    assert game.coordinator == 3
    assert game.mission_history[-1]["outcome"] == "sabotaged_by_deadlock"
    assert game.mission_history[-1]["coordinator"] == 2
    assert game.get_render_data()["missions"][-1].get("actions") is None


def test_live_mission_actions_are_private_and_maintainers_cannot_sabotage() -> None:
    game = _game()
    corrupt = next(seat for seat, role in enumerate(game.roles) if role == "corrupted")
    maintainer = next(seat for seat, role in enumerate(game.roles) if role == "maintainer")
    team = _team_with(game, corrupt, maintainer)
    _approve_team(game, team)

    while game.current_seat() != maintainer:
        seat = game.current_seat()
        game.apply_action({"mission": "sabotage" if seat == corrupt else "repair"})
    assert {"mission": "sabotage"} not in game.get_legal_actions(maintainer)
    with pytest.raises(IllegalMove):
        game.apply_action({"mission": "sabotage"})
    game.apply_action({"mission": "repair"})

    if game.phase == "mission":
        public = game.get_render_data()
        assert "sabotage" not in repr(public)
        assert public["mission_actions_submitted"] > 0


def test_three_repairs_award_every_maintainer_and_reveal_roles() -> None:
    game = _game()
    for _ in range(3):
        _complete_mission(game, sabotage=False)
    assert game.is_terminal()
    assert game.get_winner() == game._faction_seats("maintainer")
    assert game.get_scores()["repairs"] == 3
    terminal = game.get_render_data()
    assert terminal["winner_faction"] == "maintainer"
    assert terminal["roles"] == [
        {"seat": seat, "role": role} for seat, role in enumerate(game.roles)
    ]
    assert all("actions" in mission for mission in terminal["missions"])
    assert "maintainer faction wins" in game.summary()
    with pytest.raises(IllegalMove, match="game already ended"):
        game.apply_action({"resign": True})


def test_three_sabotages_award_every_corrupted_agent() -> None:
    game = _game()
    for _ in range(3):
        _complete_mission(game, sabotage=True)
    assert game.is_terminal()
    assert game.get_winner() == game._faction_seats("corrupted")
    assert game.get_scores()["sabotages"] == 3
    assert game.get_render_data()["winner_faction"] == "corrupted"
    assert all(mission["sabotages"] >= 1 for mission in game.mission_history)


def test_resignation_awards_the_opposing_faction() -> None:
    game = _game()
    resigning = game.current_seat()
    game.apply_action({"resign": True})
    assert game.get_winner() == game._opposing_faction(resigning)
    assert game.get_render_data()["terminal"] is True


def test_timeout_awards_the_opposing_faction() -> None:
    game = _game()
    timed_out = game.current_seat()
    game._clock_remaining_ms[timed_out] = 0
    game._clock_started_at = None
    game.timeout_loss(timed_out)
    assert game.get_winner() == game._opposing_faction(timed_out)
    assert "timeout" in game.summary()


def test_observations_and_terminal_history_are_defensive_copies() -> None:
    game = _game()
    _complete_mission(game, sabotage=False)
    render = game.get_render_data()
    private = game.observe(0)
    render["players"][0]["name"] = "poisoned"
    render["missions"][0]["team"].clear()
    private["state"]["your_mission_actions"].clear()
    assert game.get_render_data()["players"][0]["name"] == "Agent 0"
    assert game.get_render_data()["missions"][0]["team"]
    assert game.observe(0)["state"]["your_mission_actions"]


def test_replay_from_actions_is_deterministic() -> None:
    game = _game(seed=991)
    actions: list[dict[str, Any]] = []
    while not game.is_terminal():
        legal = game.get_legal_actions(game.current_seat())
        action = next(candidate for candidate in legal if candidate != {"resign": True})
        actions.append(deepcopy(action))
        game.apply_action(action)
    expected = game.get_render_data()

    replay = _game(seed=991)
    for action in actions:
        replay.apply_action(action)
    assert replay.get_render_data() == expected
    assert len(actions) <= 125


@pytest.mark.parametrize("perspective", [-1, True, 6, "0"])
def test_invalid_private_perspectives_fail_closed(perspective: Any) -> None:
    with pytest.raises(ValueError):
        _game().observe(perspective)
