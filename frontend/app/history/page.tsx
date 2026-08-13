"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";
import type { GameInfo } from "@/lib/types";
import MatchHistory from "@/components/MatchHistory";

export default function HistoryPage() {
  const [games, setGames] = useState<GameInfo[]>([]);
  const [game, setGame] = useState("");

  useEffect(() => {
    apiGet<GameInfo[]>("/games")
      .then(setGames)
      .catch(() => setGames([]));
  }, []);

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-end gap-3">
        <div>
          <h1 className="mb-1 text-2xl">Arcade history</h1>
          <p className="muted mb-0">
            Every completed game, with its durable result and replay.
          </p>
        </div>
        <label className="ml-auto flex flex-col gap-1 text-sm text-muted">
          Game
          <select
            value={game}
            onChange={(event) => setGame(event.target.value)}
            className="min-w-48"
          >
            <option value="">All games</option>
            {games.map((entry) => (
              <option key={entry.game} value={entry.game}>
                {entry.name}
              </option>
            ))}
          </select>
        </label>
      </header>
      <MatchHistory
        key={game || "all"}
        game={game}
        title={game ? `${game} history` : "All completed games"}
      />
    </section>
  );
}
