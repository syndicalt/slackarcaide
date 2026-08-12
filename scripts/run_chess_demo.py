#!/usr/bin/env python3
"""Run a live Chess match between two API agents vs the live backend so it can
be watched on the web UI at /match/{id}.

Registers two agents, creates a turn-based chess match, then drives both seats
with a simple 1-ply heuristic: reconstruct the position from the observation's
FEN (python-chess), prefer checkmates, then captures, then checks, then pawn
pushes, weighted randomly so games vary. Moves are paced for spectators.

Usage:  python scripts/run_chess_demo.py [MOVE_DELAY_SECONDS]
Env:    ARCADE_DEMO_BASE (default http://127.0.0.1:8098)
"""

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

import chess

BASE = os.environ.get("ARCADE_DEMO_BASE", "http://127.0.0.1:8098")
_base_url = urlsplit(BASE)
if _base_url.scheme not in {"http", "https"} or not _base_url.netloc:
    raise SystemExit("ARCADE_DEMO_BASE must be an absolute HTTP(S) URL")
MOVE_DELAY = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0

PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


def req(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(  # noqa: S310 - BASE is restricted to HTTP(S) below
        BASE + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:  # noqa: S310
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return {"_http_error": e.code, **json.load(e)}
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            return {"_http_error": e.code}


def choose_move(fen: str) -> dict:
    """1-ply heuristic over the authoritative FEN: mate > capture > check >
    pawn push, with random tie-breaking. Returns the API action dict."""
    board = chess.Board(fen)
    best, best_score = [], -(10**9)
    for move in board.legal_moves:
        score = random.random()  # noqa: S311 - randomized demo move selection
        if board.gives_check(move):
            score += 5
        if board.is_capture(move):
            victim = board.piece_at(move.to_square)
            if victim is None and board.is_en_passant(move):
                victim = chess.Piece(chess.PAWN, not board.turn)
            score += 10 + (PIECE_VALUES[victim.piece_type] if victim else 0)
        if move.promotion:
            score += 20
        if board.piece_type_at(move.from_square) == chess.PAWN:
            score += 1
        board.push(move)
        if board.is_checkmate():
            score += 10**6
        board.pop()
        if score > best_score:
            best, best_score = [move], score
        elif score == best_score:
            best.append(move)
    move = random.choice(best)  # noqa: S311 - randomized demo move selection
    return {
        "from": chess.square_name(move.from_square),
        "to": chess.square_name(move.to_square),
        "promotion": chess.piece_symbol(move.promotion) if move.promotion else None,
    }


def main():
    ts = str(int(time.time()))[-6:]
    ra = req("POST", "/agents/register", {"display_name": f"Kasparov-{ts}"})
    rb = req("POST", "/agents/register", {"display_name": f"DeepBlue-{ts}"})
    key_a, key_b = ra["api_key"], rb["api_key"]
    print(f"registered Kasparov-{ts} (white) / DeepBlue-{ts} (black)")

    m = req("POST", "/matches", {"game_type": "chess"}, key_a)
    if "_http_error" in m:
        raise SystemExit(f"create failed: {m}")
    mid = m["id"]
    j = req("POST", f"/matches/{mid}/join", {}, key_b)
    if "_http_error" in j:
        raise SystemExit(f"join failed: {j}")
    print(f"created chess id={mid} status={j['status']}")
    print(f"match page: http://127.0.0.1:3000/match/{mid}")

    keys = {0: key_a, 1: key_b}
    names = {0: f"Kasparov-{ts}", 1: f"DeepBlue-{ts}"}
    while True:
        d = req("GET", f"/matches/{mid}")
        if d.get("status") != "running":
            break
        s = req("GET", f"/matches/{mid}/state")
        st = s.get("state") or {}
        fen = st.get("fen")
        seat = st.get("turn")
        if not fen or seat not in keys:
            time.sleep(0.3)
            continue
        action = choose_move(fen)
        r = req("POST", f"/matches/{mid}/action", {"action": action}, keys[seat])
        if "_http_error" in r:
            time.sleep(0.3)
            continue
        lm = r.get("last_move") or {}
        print(
            f"move {st.get('move_number')}: {names[seat]} plays {lm.get('san', action)}"
            f"{' — ' + r['summary'] if st.get('check') else ''}"
        )
        time.sleep(MOVE_DELAY)

    fin = req("GET", f"/matches/{mid}")
    print("=== finished ===")
    print(
        json.dumps(
            {"status": fin.get("status"), "result": fin.get("result")},
            indent=2,
            default=str,
        )[:400]
    )
    print(f"match page: http://127.0.0.1:3000/match/{mid}")


if __name__ == "__main__":
    main()
