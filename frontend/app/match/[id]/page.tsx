"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiGet } from "@/lib/api";
import { useObservation } from "@/lib/hooks";
import { agentLabel, useAgentNames } from "@/lib/names";
import { errMsg } from "@/lib/errors";
import type { Match } from "@/lib/types";
import EngineCanvas from "@/components/render/EngineCanvas";
import Chat from "@/components/Chat";

/**
 * Spectator view of a single match. Agents drive the game through the API;
 * this page only renders live state and lets spectators comment.
 */
export default function MatchPage() {
  const { id } = useParams<{ id: string }>();
  const { observation, error, status } = useObservation(id);

  const [detail, setDetail] = useState<Match | null>(null);
  const [detailError, setDetailError] = useState("");

  useEffect(() => {
    apiGet<Match>(`/matches/${id}`)
      .then(setDetail)
      .catch((e) => setDetailError(errMsg(e)));
  }, [id]);

  const game = observation?.game || detail?.game_type || "unknown";
  const statusText = observation?.status || detail?.status || "lobby";
  const players = observation?.players?.length
    ? observation.players
    : detail?.players || [];
  // players carry a display-name snapshot for matches created after that
  // landed; legacy rows fall back to resolving the id once via /agents/{id}
  const names = useAgentNames(players.map((p) => p.agent_id));

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link href="/" className="ghost rounded border px-3 py-1.5 text-sm">
          ← Lobby
        </Link>
        <h1 className="mb-0 text-xl capitalize">{game}</h1>
        <span className={`badge ${statusText}`}>{statusText}</span>
        <span className={`badge ${status === "open" ? "running" : "lobby"}`}>
          {status === "open" ? "live" : "polling"}
        </span>
        <span className="muted small mono">/match/{id.slice(0, 8)}</span>
        {statusText === "finished" && (
          <Link
            href={`/replay/${id}`}
            className="neon rounded px-3 py-1.5 text-sm"
          >
            Watch replay
          </Link>
        )}
      </div>

      {detail && (
        <p className="muted small">
          {typeof detail.seed === "number"
            ? `seed ${detail.seed}`
            : "seed hidden"}{" "}
          · mode {detail.mode} · {detail.players.length} player
          {detail.players.length === 1 ? "" : "s"}
        </p>
      )}
      {detailError && <p className="error">{detailError}</p>}
      {error && <p className="warn">{error}</p>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <div className="panel neon">
            <EngineCanvas game={game} render={observation?.render ?? null} />
          </div>

          {observation?.summary && (
            <div className="panel">
              <h2 className="mb-0 text-sm">Status</h2>
              <p className="muted mb-0">{observation.summary}</p>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <div className="panel">
            <h2>Players</h2>
            {players.length > 0 ? (
              <ul className="list">
                {players.map((p) => (
                  <li key={p.agent_id} className="!py-2">
                    <div className="grow">
                      <Link
                        href={`/agents/${p.agent_id}`}
                        className="font-semibold text-accent hover:underline"
                      >
                        {p.name || agentLabel(p.agent_id, names)}
                      </Link>
                      <div className="muted small">seat {p.seat}</div>
                    </div>
                    {p.side && <span className="badge">{p.side}</span>}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="muted">No players yet.</p>
            )}
            {observation?.scores &&
              Object.keys(observation.scores).length > 0 && (
                <div className="mt-3">
                  <h2 className="text-sm">Scores</h2>
                  <pre className="muted mono small bg-[#0b1018] rounded p-2 whitespace-pre-wrap">
                    {JSON.stringify(observation.scores, null, 2)}
                  </pre>
                </div>
              )}
          </div>

          <Chat channel={id} title="Match thread" />
        </div>
      </div>
    </section>
  );
}
