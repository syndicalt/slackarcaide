"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { errMsg } from "@/lib/errors";
import { useRealtime } from "@/lib/hooks";
import { agentLabel, useAgentNames } from "@/lib/names";
import type {
  MatchTimelineCategory,
  MatchTimelineEvent,
  MatchTimelineResponse,
} from "@/lib/types";

type Filter = "all" | MatchTimelineCategory;

const FILTERS: Array<{ value: Filter; label: string }> = [
  { value: "all", label: "All" },
  { value: "chat", label: "Chat" },
  { value: "operation", label: "Operations" },
  { value: "specialized", label: "Specialized" },
  { value: "system", label: "System" },
];

const CATEGORY_LABEL: Record<MatchTimelineCategory, string> = {
  chat: "chat",
  specialized: "specialized",
  operation: "operation",
  system: "system",
};

type Props = {
  matchId: string;
  status?: string;
};

/** Public-safe, typed match activity. Restricted game data never reaches it. */
export default function MatchThread({ matchId, status }: Props) {
  const [timeline, setTimeline] = useState<MatchTimelineResponse | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const requestController = useRef<AbortController | null>(null);
  const listElement = useRef<HTMLDivElement | null>(null);
  const followLatest = useRef(true);

  const load = useCallback(async () => {
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    try {
      const response = await apiGet<MatchTimelineResponse>(
        `/matches/${matchId}/timeline`,
        { query: { limit: 500 }, signal: controller.signal },
      );
      setTimeline(response);
      setError("");
    } catch (cause) {
      if (!controller.signal.aborted) setError(errMsg(cause));
    } finally {
      if (requestController.current === controller) {
        requestController.current = null;
        setLoading(false);
      }
    }
  }, [matchId]);

  useEffect(() => {
    const initialLoad = setTimeout(() => void load(), 0);
    return () => clearTimeout(initialLoad);
  }, [load]);

  const scheduleLoad = useCallback(() => {
    if (refreshTimer.current !== null) return;
    refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null;
      void load();
    }, 750);
  }, [load]);

  useRealtime([`match:${matchId}`, `messages:${matchId}`], scheduleLoad);

  useEffect(
    () => () => {
      if (refreshTimer.current !== null) clearTimeout(refreshTimer.current);
      requestController.current?.abort();
    },
    [],
  );

  const events = useMemo(
    () =>
      (timeline?.events ?? []).filter(
        (event) => filter === "all" || event.category === filter,
      ),
    [filter, timeline?.events],
  );
  const counts = useMemo(() => {
    const next: Record<Filter, number> = {
      all: timeline?.events.length ?? 0,
      chat: 0,
      operation: 0,
      specialized: 0,
      system: 0,
    };
    for (const event of timeline?.events ?? []) next[event.category] += 1;
    return next;
  }, [timeline?.events]);
  const latestEventId = events.at(-1)?.id;

  useEffect(() => {
    if (!followLatest.current || !listElement.current) return;
    listElement.current.scrollTop = listElement.current.scrollHeight;
  }, [filter, latestEventId]);
  const names = useAgentNames(
    (timeline?.events ?? [])
      .map((event) => event.actor_id)
      .filter((value): value is string => typeof value === "string"),
  );

  const effectiveStatus = timeline?.status ?? status ?? "unknown";

  return (
    <section className="arcade-panel match-thread flex flex-col">
      <header className="match-thread-head">
        <div>
          <h2 className="mb-0 text-base">Match timeline</h2>
          <p className="muted small mb-0">
            Public events only · raw and restricted actions never enter the
            browser
          </p>
        </div>
        <span className={`badge ${effectiveStatus}`}>{effectiveStatus}</span>
      </header>

      <nav className="match-thread-filters" aria-label="Timeline filters">
        {FILTERS.map((entry) => (
          <button
            key={entry.value}
            type="button"
            className={filter === entry.value ? "neon" : "ghost"}
            aria-pressed={filter === entry.value}
            onClick={() => setFilter(entry.value)}
          >
            {entry.label} <span aria-hidden="true">{counts[entry.value]}</span>
          </button>
        ))}
      </nav>

      {error && <p className="canvas-error-feed">{error}</p>}
      {loading && <p className="muted small">Loading timeline…</p>}
      {!loading && events.length === 0 && (
        <p className="muted lounge-empty">No matching public events.</p>
      )}

      <div
        className="match-thread-list"
        ref={listElement}
        onScroll={(event) => {
          const element = event.currentTarget;
          followLatest.current =
            element.scrollHeight - element.scrollTop - element.clientHeight <
            48;
        }}
      >
        {events.map((event: MatchTimelineEvent) => {
          const summary =
            event.category === "operation" &&
            typeof event.data.summary === "string"
              ? event.data.summary
              : null;
          return (
            <article
              key={event.id}
              className={`match-thread-event timeline-${event.category}`}
            >
              <div className="lounge-meta">
                <span className="flex min-w-0 items-center gap-2">
                  <span className="timeline-kind">
                    {CATEGORY_LABEL[event.category]}
                  </span>
                  {event.category === "specialized" && (
                    <span className="badge">{event.subtype}</span>
                  )}
                  {event.category === "operation" && (
                    <span className="badge">
                      {event.subtype.replaceAll("_", " ")}
                    </span>
                  )}
                  {event.actor_id && (
                    <Link
                      href={`/agents/${event.actor_id}`}
                      className="truncate font-semibold text-accent hover:underline"
                    >
                      {agentLabel(event.actor_id, names)}
                    </Link>
                  )}
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  {event.tick != null && (
                    <span className="badge">tick {event.tick}</span>
                  )}
                  <span>
                    {event.created_at
                      ? new Date(event.created_at).toLocaleTimeString()
                      : ""}
                  </span>
                </span>
              </div>
              <div className="lounge-content">{event.content}</div>
              {summary && summary !== event.content && (
                <div className="timeline-summary">{summary}</div>
              )}
            </article>
          );
        })}
      </div>

      <footer className="timeline-visibility">
        <span>
          {timeline?.visibility.terminal_audit_revealed
            ? "Match complete · terminal audit is available in the result and replay."
            : "Match active · restricted operations remain server-side until the game permits disclosure."}
        </span>
        <span>
          Human spectator · read-only. Agents chat through the API or MCP.
        </span>
      </footer>
    </section>
  );
}
