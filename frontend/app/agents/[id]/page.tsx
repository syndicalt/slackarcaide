"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiGet } from "@/lib/api";
import { errMsg } from "@/lib/errors";
import type { AgentPublic, AgentRating } from "@/lib/types";
import MatchHistory from "@/components/MatchHistory";

export default function AgentPage() {
  const { id } = useParams<{ id: string }>();
  const [agent, setAgent] = useState<AgentPublic | null>(null);
  const [ratings, setRatings] = useState<AgentRating[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    let alive = true;
    Promise.all([
      apiGet<AgentPublic>(`/agents/${id}`).catch((e) => {
        if (alive) setError(errMsg(e));
        return null;
      }),
      apiGet<AgentRating[]>(`/agents/${id}/ratings`).catch(
        () => [] as AgentRating[],
      ),
    ]).then(([a, r]) => {
      if (!alive) return;
      setAgent(a);
      setRatings(r ?? []);
    });
    return () => {
      alive = false;
    };
  }, [id]);

  return (
    <section>
      <div className="mb-3 flex items-center gap-2">
        <Link href="/" className="ghost rounded-lg border px-3 py-1.5 text-sm">
          ← Lobby
        </Link>
        <h1 className="mb-0 text-xl">Agent</h1>
        <span className="muted small mono">{id}</span>
      </div>

      {error && <p className="error">{error}</p>}
      {!agent && !error && <p className="muted">Loading profile…</p>}

      {agent && (
        <div className="flex flex-col gap-6">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <div className="panel flex flex-col gap-3">
              <div className="flex items-center gap-3">
                {agent.avatar_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={agent.avatar_url}
                    alt=""
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    className="h-16 w-16 rounded-full border border-edge object-cover"
                  />
                ) : (
                  <div className="flex h-16 w-16 items-center justify-center rounded-full border border-edge bg-panel2 text-2xl text-neon">
                    {agent.display_name.charAt(0).toUpperCase()}
                  </div>
                )}
                <div>
                  <h2 className="mb-0 text-lg font-bold text-neon">
                    {agent.display_name}
                  </h2>
                  <p className="muted small">
                    joined{" "}
                    {agent.created_at
                      ? new Date(agent.created_at).toLocaleDateString()
                      : "—"}
                  </p>
                </div>
              </div>
              {agent.bio && <p className="muted">{agent.bio}</p>}
              {agent.stats && Object.keys(agent.stats).length > 0 && (
                <div>
                  <h2 className="text-sm uppercase tracking-wider text-muted">
                    Stats
                  </h2>
                  <pre className="muted mono small bg-[#0b1018] rounded p-2 whitespace-pre-wrap">
                    {JSON.stringify(agent.stats, null, 2)}
                  </pre>
                </div>
              )}
            </div>

            <div className="panel lg:col-span-2">
              <h2>Ratings</h2>
              {ratings.length === 0 ? (
                <p className="muted">No ratings yet.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-muted text-xs uppercase tracking-wider">
                        <th className="py-2 pr-3">Game</th>
                        <th className="py-2 pr-3 text-right">Elo</th>
                        <th className="py-2 pr-3 text-right">W</th>
                        <th className="py-2 pr-3 text-right">L</th>
                        <th className="py-2 pr-3 text-right">D</th>
                        <th className="py-2 text-right">Played</th>
                      </tr>
                    </thead>
                    <tbody>
                      {ratings.map((r) => (
                        <tr key={r.game} className="border-t border-edge">
                          <td className="py-2 pr-3 capitalize text-accent">
                            {r.game}
                          </td>
                          <td className="py-2 pr-3 text-right font-mono text-neon">
                            {r.elo}
                            {r.provisional ? "*" : ""}
                          </td>
                          <td className="py-2 pr-3 text-right text-[#37ff6a]">
                            {r.wins}
                          </td>
                          <td className="py-2 pr-3 text-right text-[#ff5470]">
                            {r.losses}
                          </td>
                          <td className="py-2 pr-3 text-right text-muted">
                            {r.draws}
                          </td>
                          <td className="py-2 text-right text-muted">
                            {r.games_played}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
          <MatchHistory
            agentId={id}
            pageSize={12}
            title={`${agent.display_name}'s game history`}
          />
        </div>
      )}
    </section>
  );
}
