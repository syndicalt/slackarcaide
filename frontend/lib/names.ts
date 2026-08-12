"use client";

import { useEffect, useState } from "react";
import { apiGet } from "@/lib/api";

/**
 * Resolve agent UUIDs to display names, fetching `/agents/{id}` once per id
 * and caching module-wide (names are effectively immutable — there is no
 * rename endpoint). Components render the short id until the name lands.
 * Failed lookups cache "" so a missing agent never refetches in a loop.
 */
const cache = new Map<string, string>();

export function useAgentNames(
  ids: readonly (string | null | undefined)[]
): Record<string, string> {
  const [version, setVersion] = useState(0);
  const key = ids.filter(Boolean).sort().join("|");

  useEffect(() => {
    const missing = key
      .split("|")
      .filter(Boolean)
      .filter((id) => !cache.has(id));
    if (missing.length === 0) return;
    let alive = true;
    Promise.all(
      missing.map((id) =>
        apiGet<{ display_name: string }>(`/agents/${id}`)
          .then((a) => cache.set(id, a.display_name))
          .catch(() => cache.set(id, ""))
      )
    ).then(() => {
      if (alive) setVersion((v) => v + 1);
    });
    return () => {
      alive = false;
    };
  }, [key]);

  void version; // re-render trigger; reads hit the cache below
  const out: Record<string, string> = {};
  for (const id of key.split("|").filter(Boolean)) {
    const name = cache.get(id);
    if (name) out[id] = name;
  }
  return out;
}

/** Display label for an agent: resolved name, else truncated id. */
export function agentLabel(id: string, names: Record<string, string>): string {
  return names[id] || (id.length > 8 ? `${id.slice(0, 8)}…` : id);
}
