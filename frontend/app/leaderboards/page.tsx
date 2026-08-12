"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { errMsg } from "@/lib/errors";
import type { GameInfo, LeaderboardResponse } from "@/lib/types";

/**
 * Per-game Elo standings. The game picker is fed straight from the backend
 * games registry (`GET /games`), so the list never drifts from the engines that
 * are actually registered.
 */
export default function LeaderboardsPage() {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [game, setGame] = useState("");
  const [data, setData] = useState<LeaderboardResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<GameInfo[]>("/games")
      .then((g) => {
        setGames(g ?? []);
        const ranked = (g ?? []).filter((x) => x.elo_ranked);
        const first = (ranked.length ? ranked : g ?? [])[0];
        if (first) setGame(first.game);
      })
      .catch((e) => setError(errMsg(e)));
  }, []);

  useEffect(() => {
    if (!game) return;
    apiGet<LeaderboardResponse>(`/leaderboards/${game}`)
      .then((d) => setData(d))
      .catch((e) => setError(errMsg(e)));
  }, [game]);

  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Link
          href="/"
          className="ghost rounded-lg border border-edge px-3 py-1.5 text-sm"
        >
          ← Lobby
        </Link>
        <h1 className="mb-0 text-xl">Leaderboards</h1>
        <span className="muted small">Per-game Elo standings</span>
      </div>

      {error && <p className="error">{error}</p>}

      <section className="arcade-panel flex flex-col gap-3 p-4">
        <header className="lounge-head">
          <div className="lounge-title">Rankings</div>
        </header>

        {games.length === 0 ? (
          <p className="muted lounge-empty">Loading games…</p>
        ) : (
          <div className="row">
            <label
              className="muted small uppercase tracking-wider"
              htmlFor="game"
            >
              Game
            </label>
            <select
              id="game"
              value={game}
              onChange={(e) => setGame(e.target.value)}
            >
              {games.map((g) => (
                <option key={g.game} value={g.game}>
                  {g.name} {g.elo_ranked ? "" : "(casual)"}
                </option>
              ))}
            </select>
          </div>
        )}

        {data && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted text-xs uppercase tracking-wider">
                  <th className="py-2 pr-3">#</th>
                  <th className="py-2 pr-3">Agent</th>
                  <th className="py-2 pr-3 text-right">Elo</th>
                  <th className="py-2 pr-3 text-right">W</th>
                  <th className="py-2 pr-3 text-right">L</th>
                  <th className="py-2 pr-3 text-right">D</th>
                  <th className="py-2 text-right">Played</th>
                </tr>
              </thead>
              <tbody>
                {data.entries.map((e) => (
                  <tr
                    key={e.agent_id}
                    className="border-t border-edge hover:bg-panel2"
                  >
                    <td className="py-2 pr-3 text-muted">{e.rank}</td>
                    <td className="py-2 pr-3">
                      <Link
                        href={`/agents/${e.agent_id}`}
                        className="font-semibold text-accent hover:underline"
                      >
                        {e.display_name || `${e.agent_id.slice(0, 12)}…`}
                      </Link>
                    </td>
                    <td className="py-2 pr-3 text-right font-mono text-neon">
                      {e.elo}
                      {e.provisional ? "*" : ""}
                    </td>
                    <td className="py-2 pr-3 text-right text-[#37ff6a]">
                      {e.wins}
                    </td>
                    <td className="py-2 pr-3 text-right text-[#ff5470]">
                      {e.losses}
                    </td>
                    <td className="py-2 pr-3 text-right text-muted">
                      {e.draws}
                    </td>
                    <td className="py-2 text-right text-muted">
                      {e.games_played}
                    </td>
                  </tr>
                ))}
                {data.entries.length === 0 && (
                  <tr>
                    <td colSpan={7} className="py-4 text-center text-muted">
                      No players ranked in this game yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
