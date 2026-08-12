#!/usr/bin/env python3
"""Run a full, decisive Connect Four match between two API agents vs the live
backend. Exercises the same agent lifecycle the chess demo uses (register,
create, join, state, action, finish) but the game itself always terminates
(win or full-board draw), so the match reliably concludes and Elo updates.

AI for the first-to-join agent (seat 0): complete an own line, block the
opponent's immediate win, otherwise drop toward the center. The opponent
(seat 1) plays its first legal action.
"""
import json
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8098"
ROWS, COLS = 6, 7


def req(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            return {"_http_error": e.code, **json.load(e)}
        except Exception:
            return {"_http_error": e.code}


def drop(board, c, tok):
    b = [row[:] for row in board]
    for r in range(ROWS - 1, -1, -1):
        if not b[r][c]:
            b[r][c] = tok
            return b
    return None


def wins(board, tok):
    for r in range(ROWS):
        for c in range(COLS):
            for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                if all(0 <= r + dr * k < ROWS and 0 <= c + dc * k < COLS
                       and board[r + dr * k][c + dc * k] == tok for k in range(4)):
                    return True
    return False


def pick(board, legal, my_tok):
    cols = [x["column"] for x in legal]
    if my_tok is None:
        # opening move: center
        return sorted(cols, key=lambda c: abs(c - 3))[0]
    for c in cols:
        b = drop(board, c, my_tok)
        if b and wins(b, my_tok):
            return c
    opp = "1" if my_tok == "0" else "0"
    for c in cols:
        b = drop(board, c, opp)
        if b and wins(b, opp):
            return c
    return sorted(cols, key=lambda c: (abs(c - 3), -c))[0]


def token_in_col(board, c):
    for r in range(ROWS - 1, -1, -1):
        if board[r][c]:
            return board[r][c]
    return None


def main():
    ts = str(int(time.time()))[-6:]
    ra = req("POST", "/agents/register", {"display_name": f"C4First-{ts}"})
    rb = req("POST", "/agents/register", {"display_name": f"C4Second-{ts}"})
    key_a, key_b = ra["api_key"], rb["api_key"]
    print(f"registered C4First-{ts} / C4Second-{ts}")

    m = None
    for _try in range(30):
        m = req("POST", "/matches", {"game_type": "connect_four", "mode": "turnbased",
                                     "config": {}}, key_a)
        if m.get("_http_error") != 401:
            break
        time.sleep(0.2)
    if not m or "_http_error" in m:
        raise SystemExit(f"create failed: {m}")
    mid = m["id"]
    j = None
    for _try in range(30):
        j = req("POST", f"/matches/{mid}/join", {}, key_b)
        if "_http_error" not in j:
            break
        time.sleep(0.2)
    if "_http_error" in j:
        raise SystemExit(f"join failed: {j}")
    print(f"created connect_four id={mid} status after join={j['status']}")

    keys = {0: key_a, 1: key_b}
    my_tok = None
    plies = 0
    for _ in range(64):
        d = req("GET", f"/matches/{mid}")
        if d.get("status") != "running":
            break
        s = req("GET", f"/matches/{mid}/state")
        st = s.get("state") or {}
        board = st.get("board")
        turn = st.get("turn")
        legal = s.get("legal_actions") or []
        if turn is None or not board:
            time.sleep(0.15)
            continue
        if not legal:
            time.sleep(0.15)
            continue
        if turn == 0:
            c = pick(board, legal, my_tok)
        else:
            c = legal[0]["column"]
        mv = {"column": c}
        a = req("POST", f"/matches/{mid}/action", {"action": mv,
                                                   "intent": f"seat{turn} drop col {c}"},
                                                keys[turn])
        if "_http_error" in a:
            time.sleep(0.1)
            continue
        plies += 1
        if turn == 0 and my_tok is None:
            s2 = req("GET", f"/matches/{mid}/state")
            my_tok = token_in_col((s2.get("state") or {}).get("board") or [], c)
        print(f"ply {plies:>3} player {turn} col {c}")
        time.sleep(0.05)

    fin = req("GET", f"/matches/{mid}")
    result = fin.get("result") or {}
    print("=== finished ===")
    print(json.dumps({
        "status": fin.get("status"),
        "result_reason": result.get("reason"),
        "winner_seats": result.get("winner_seats"),
        "winner_agents": result.get("winner_agents"),
        "scores": result.get("scores"),
    }, indent=2))
    print(f"match page: http://127.0.0.1:3000/match/{mid}")


if __name__ == "__main__":
    main()
