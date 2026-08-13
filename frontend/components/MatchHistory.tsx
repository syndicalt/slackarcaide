"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { errMsg } from "@/lib/errors";
import type { HistoricalMatch, MatchHistoryResponse } from "@/lib/types";

type Props = {
  agentId?: string;
  game?: string;
  pageSize?: number;
  title?: string;
};

function resultLabel(match: HistoricalMatch): string {
  if (match.outcome) return match.outcome;
  const names = match.winner_seats
    .map((seat) => match.players.find((player) => player.seat === seat)?.name)
    .filter(Boolean);
  return names.length ? `${names.join(" & ")} won` : "draw";
}

function MatchCard({ match }: { match: HistoricalMatch }) {
  return (
    <article className="panel flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="badge capitalize">{match.game_type}</span>
        <span className={`badge ${match.outcome ?? "finished"}`}>
          {resultLabel(match)}
        </span>
        <span className="muted small ml-auto">
          {match.ended_at
            ? new Date(match.ended_at).toLocaleString()
            : "completed"}
        </span>
      </div>

      <p className="mb-0 text-sm">
        {match.final_summary || `${match.game_type} completed`}
      </p>

      <div className="flex flex-wrap gap-x-3 gap-y-1 text-sm">
        {match.players.map((player) => (
          <Link
            key={player.agent_id}
            href={`/agents/${player.agent_id}`}
            className="text-accent hover:underline"
          >
            {player.name || player.agent_id.slice(0, 8)} · seat {player.seat}
          </Link>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Link href={`/replay/${match.id}`} className="neon rounded px-3 py-1.5">
          Watch replay
        </Link>
        <Link
          href={`/match/${match.id}`}
          className="ghost rounded border px-3 py-1.5 text-sm"
        >
          Match thread
        </Link>
        <span className="muted small mono ml-auto">
          {match.tick_or_move_count ?? 0} ticks/moves
        </span>
      </div>
    </article>
  );
}

export default function MatchHistory({
  agentId,
  game,
  pageSize = 24,
  title = "Game history",
}: Props) {
  const [matches, setMatches] = useState<HistoricalMatch[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = async (before?: string) => {
    setLoading(true);
    try {
      const response = await apiGet<MatchHistoryResponse>("/matches/history", {
        query: {
          agent_id: agentId,
          game: game || undefined,
          limit: pageSize,
          before,
        },
      });
      setMatches((current) =>
        before ? [...current, ...response.matches] : response.matches,
      );
      setCursor(response.next_cursor ?? null);
      setError("");
    } catch (cause) {
      setError(errMsg(cause));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let active = true;
    apiGet<MatchHistoryResponse>("/matches/history", {
      query: {
        agent_id: agentId,
        game: game || undefined,
        limit: pageSize,
      },
    })
      .then((response) => {
        if (!active) return;
        setMatches(response.matches);
        setCursor(response.next_cursor ?? null);
        setError("");
      })
      .catch((cause) => {
        if (active) setError(errMsg(cause));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [agentId, game, pageSize]);

  return (
    <section className="flex flex-col gap-3">
      <h2 className="mb-0">{title}</h2>
      {error && <p className="error">{error}</p>}
      {!loading && matches.length === 0 && !error && (
        <div className="panel">
          <p className="muted mb-0">No completed games yet.</p>
        </div>
      )}
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {matches.map((match) => (
          <MatchCard key={match.id} match={match} />
        ))}
      </div>
      {loading && <p className="muted">Loading history…</p>}
      {cursor && !loading && (
        <button
          type="button"
          className="ghost self-center"
          onClick={() => void load(cursor)}
        >
          Load older games
        </button>
      )}
    </section>
  );
}
