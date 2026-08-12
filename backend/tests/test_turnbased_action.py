"""Regression tests for MatchManager.submit_action on turn-based games.

Two past bugs lived on the pay path for `POST /matches/{id}/action`:
  1. `HTTPException(400, "invalid_move", detail=...)` passed the third positional
     arg (which Starlette treats as `headers`) *and* a keyword `detail`, so ANY
     submitted action for a turn-based match raised TypeError instead of a
     clean 400.
  2. The legality check used exact dict equality against engine candidates that
     carry optional keys set to `None` (e.g. chess `"promotion": None`), so a
     client that omits the optional key (a plain `{"from": "e2", "to": "e4"}`)
     was rejected as an illegal move even though it is legal.

These tests exercise the manager legality path directly with real engines and
lightweight match/agent objects, so no database is required.
"""
import random
import uuid

import pytest
from fastapi import HTTPException

from app.engine.games.chess import Chess
from app.engine.games.go import Go
from app.engine.match_manager import MatchManager


def _seats(n: int) -> list[dict]:
    return [
        {"agent_id": str(i), "seat": i, "side": f"side{i}", "name": f"agent{i}"}
        for i in range(n)
    ]


from types import SimpleNamespace


def _agent(agent_id: str):
    return SimpleNamespace(id=agent_id)


async def _manager_map(game_cls, players: list[dict]) -> tuple[MatchManager, uuid.UUID, dict]:
    """A MatchManager whose engine host is pre-seeded for one turn-based match."""
    mgr = MatchManager()
    match_id = uuid.uuid4()
    engine = game_cls(config={}, seed=1, seats=list(players))
    mgr._engines[match_id] = engine
    mgr._buffers[match_id] = {}
    return mgr, match_id


@pytest.mark.asyncio
async def test_chess_legal_move_omitting_promotion_is_accepted():
    """White's opening e2-e4 (no 'promotion' key) must not crash and must buffer."""
    players = _seats(2)
    mgr, match_id = await _manager_map(Chess, players)
    match = type("Match", (), {
        "id": match_id, "status": "running", "players": players,
        "game_type": "chess", "mode": "turnbased",
    })()
    white = _agent(players[0]["agent_id"])

    obs = await mgr.submit_action(match, white, {"from": "e2", "to": "e4"})
    # accepted → buffered for the white seat and observation returned
    assert mgr._buffers[match_id][0]
    assert obs["game"] == "chess"


@pytest.mark.asyncio
async def test_illegal_turnbased_move_returns_400_not_crash():
    """An out-of-account move (white reuses e2-e4 after it's no longer legal) must
    yield HTTP 400 with a detail string, never a TypeError."""
    players = _seats(2)
    mgr, match_id = await _manager_map(Chess, players)
    match = type("Match", (), {
        "id": match_id, "status": "running", "players": players,
        "game_type": "chess", "mode": "turnbased",
    })()
    white = _agent(players[0]["agent_id"])

    # first e2-e4 is legal
    await mgr.submit_action(match, white, {"from": "e2", "to": "e4"})
    # placing a queen's pawn on a4 from e2 is illegal; still white's turn
    with pytest.raises(HTTPException) as exc:
        await mgr.submit_action(match, white, {"from": "e2", "to": "a5"})
    assert exc.value.status_code == 400
    assert "invalid" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_go_legal_action_shape_accepted():
    """Go legal actions are {'x','y'}; that exact shape must be accepted."""
    players = _seats(2)
    mgr, match_id = await _manager_map(Go, players)
    match = type("Match", (), {
        "id": match_id, "status": "running", "players": players,
        "game_type": "go", "mode": "turnbased",
    })()
    black = _agent(players[0]["agent_id"])

    obs = await mgr.submit_action(match, black, {"x": 4, "y": 4})
    assert mgr._buffers[match_id][0]
    assert obs["game"] == "go"


@pytest.mark.asyncio
async def test_verbatim_legal_action_with_none_key_accepted():
    """A client may echo the engine's own legal action verbatim, including
    optional keys set to None (chess 'promotion'), and it must be accepted.
    Regression: _match trimmed the candidate's None keys but compared to the
    untrimmed action, so the verbatim form raised 400 invalid_move."""
    players = _seats(2)
    mgr, match_id = await _manager_map(Chess, players)
    match = type("Match", (), {
        "id": match_id, "status": "running", "players": players,
        "game_type": "chess", "mode": "turnbased",
    })()
    white = _agent(players[0]["agent_id"])

    action = mgr._engines[match_id].get_legal_actions(0)[0]
    assert any(v is None for v in action.values())  # the case that used to fail

    obs = await mgr.submit_action(match, white, action)
    assert mgr._buffers[match_id][0]
    assert obs["game"] == "chess"


def test_unmoved_seat_clock_ticks_from_match_start():
    """A player who has not yet moved must still run down the clock (seeded at
    engine construction), so a passive opponent eventually times out.
    Regression: clock_ms defaulted an unknown seat's last-move time to 'now'
    every call, giving an unmoved seat a never-depleting clock."""
    import time

    engine = Go(
        config={"time_control": {"base_sec": 1, "increment_sec": 0, "enabled": True}},
        seed=1, seats=_seats(2),
    )
    time.sleep(1.2)
    assert engine.clock_ms(0) is not None
    assert engine.clock_ms(0) <= 0
