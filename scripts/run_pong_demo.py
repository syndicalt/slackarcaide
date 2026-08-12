#!/usr/bin/env python3
"""Run a live Pong match between two API agents vs the live backend so it can
be watched on the web UI at /match/{id}.

Registers two agents, creates a realtime pong match, joins the second seat,
then drives both with a simple proportional-tracking reflex (each paddle
follows the ball's y). Posting {"vy": v} each loop lets the documented noop
coast policy keep the paddle sweeping smoothly between actions, which
sustains rallies and makes the slow-start -> accelerating -> capped ball
speed visible. The match ends on a win; Elo updates for the two agents.

Usage:  python scripts/run_pong_demo.py [MAX_SECONDS]
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

BASE = os.environ.get("ARCADE_DEMO_BASE", "http://127.0.0.1:8098")
_base_url = urlsplit(BASE)
if _base_url.scheme not in {"http", "https"} or not _base_url.netloc:
    raise SystemExit("ARCADE_DEMO_BASE must be an absolute HTTP(S) URL")
MAX_SECONDS = int(sys.argv[1]) if len(sys.argv) > 1 else 600
PADDLE_H = 90.0
PADDLE_W = 14.0
H = 500.0
W = 800.0


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


def decide(seat, state):
    """Return a paddle velocity in [-1, 1]. When the ball is inbound, aim the
    paddle center at the ball's *projected* y at the wall (anticipation via the
    ball's vx/vy) so the paddle meets it instead of trailing; when outbound,
    drift back to center. Coast (noop) policy keeps the sweep smooth."""
    paddles = state.get("paddles") or [H / 2, H / 2]
    ball = state.get("ball") or {"y": H / 2, "x": W / 2, "vx": 1.0, "vy": 0.0}
    my_center = paddles[seat] + PADDLE_H / 2.0
    bx, by = ball["x"], ball["y"]
    bvx, bvy = ball.get("vx", 1.0), ball.get("vy", 0.0)
    toward = (bvx < 0 and seat == 0) or (bvx > 0 and seat == 1)
    if toward:
        wall = PADDLE_W + 6 if seat == 0 else W - PADDLE_W - 6
        ticks = abs(bx - wall) / (abs(bvx) or 1.0)
        target = by + bvy * ticks
        target = max(0.0, min(float(H), target))
    else:
        target = H / 2.0
    delta = target - my_center
    G = 70.0  # delta/G=1 => full paddle speed ~20px/tick at ~70px error
    vy = max(-1.0, min(1.0, delta / G))
    return {"vy": round(vy, 3)}


def main():
    ts = str(int(time.time()))[-6:]
    ra = req("POST", "/agents/register", {"display_name": f"PongAlpha-{ts}"})
    rb = req("POST", "/agents/register", {"display_name": f"PongBravo-{ts}"})
    key_a, key_b = ra["api_key"], rb["api_key"]
    print(f"registered PongAlpha-{ts} / PongBravo-{ts}")

    m = None
    for _try in range(30):
        m = req("POST", "/matches", {"game_type": "pong"}, key_a)
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
    print(f"created pong id={mid} status after join={j['status']}")
    print(f"match page: http://127.0.0.1:3000/match/{mid}")

    keys = {0: key_a, 1: key_b}
    started = time.time()
    last_report = 0.0
    rallies = 0
    while True:
        d = req("GET", f"/matches/{mid}")
        if d.get("status") != "running":
            break
        s = req("GET", f"/matches/{mid}/state")
        st = s.get("state") or {}
        if not st:
            time.sleep(0.05)
            continue
        for seat in (0, 1):
            a = req(
                "POST",
                f"/matches/{mid}/action",
                {"action": decide(seat, st), "intent": f"seat{seat} track"},
                keys[seat],
            )
            if "_http_error" in a:
                time.sleep(0.02)
        rallies += 1
        now = time.time()
        if now - last_report >= 1.5:
            last_report = now
            ball = st.get("ball") or {}
            v = (ball.get("vx", 0) ** 2 + ball.get("vy", 0) ** 2) ** 0.5
            scores = st.get("scores") or [0, 0]
            print(
                f"t={now - started:6.1f}s tick={st.get('tick', 0):>5} "
                f"ball_spd={v:5.1f} paddles=[{st['paddles'][0]:5.1f},{st['paddles'][1]:5.1f}] "
                f"scores={scores}"
            )
        if now - started > MAX_SECONDS:
            print("time cap reached; leaving match running")
            break
        time.sleep(0.05)

    fin = req("GET", f"/matches/{mid}")
    result = fin.get("result") or {}
    print("=== finished ===")
    print(
        json.dumps(
            {
                "status": fin.get("status"),
                "result_reason": result.get("reason"),
                "winner_seats": result.get("winner_seats"),
                "winner_agents": result.get("winner_agents"),
                "scores": result.get("scores"),
            },
            indent=2,
        )
    )
    print(f"match page: http://127.0.0.1:3000/match/{mid}")


if __name__ == "__main__":
    main()
