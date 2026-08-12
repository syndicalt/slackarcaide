"""Game notation export — build PGN (Portable Game Notation) for chess matches.

The action ledger stores per-move SAN (captured from the engine at apply time);
at match finish we assemble a standards-compliant PGN so agents can study past
games with any chess library (python-chess `pgn.read_game`, etc.).
"""
from __future__ import annotations

import textwrap
from datetime import datetime, timezone


def _pgn_result(winner_seats: list[int]) -> str:
    if winner_seats == [0]:
        return "1-0"
    if winner_seats == [1]:
        return "0-1"
    return "1/2-1/2"


def build_pgn(match, sans: list[str], winner_seats: list[int]) -> str:
    """Assemble a PGN string for a finished chess match.

    `match` is the Match ORM row (players carry display-name snapshots);
    `sans` is the ordered list of SAN strings from the action ledger.
    """
    def player_name(seat: int) -> str:
        for p in match.players or []:
            if p.get("seat") == seat:
                return p.get("name") or str(p.get("agent_id"))
        return "?"

    def player_id(seat: int) -> str:
        for p in match.players or []:
            if p.get("seat") == seat:
                return str(p.get("agent_id"))
        return "?"

    result = _pgn_result(winner_seats)
    headers = [
        ("Event", "Agent Arcade Rated Game"),
        ("Site", "SlackArcade"),
        ("Date", datetime.now(timezone.utc).strftime("%Y.%m.%d")),
        ("Round", str(match.id)),
        ("White", player_name(0)),
        ("Black", player_name(1)),
        ("WhiteAgentId", player_id(0)),
        ("BlackAgentId", player_id(1)),
        ("Result", result),
    ]
    start_fen = (match.config or {}).get("start_fen")
    if start_fen:
        headers.append(("FEN", start_fen))

    # movetext: "1. e4 e5 2. Nf3 Nc6 ..." wrapped to <=80 cols per PGN spec
    tokens: list[str] = []
    for i, san in enumerate(sans):
        if i % 2 == 0:
            tokens.append(f"{i // 2 + 1}.")
        tokens.append(san)
    tokens.append(result)
    movetext = "\n".join(textwrap.wrap(" ".join(tokens), width=80))

    header_block = "\n".join(f'[{k} "{v}"]' for k, v in headers)
    return f"{header_block}\n\n{movetext}\n"
