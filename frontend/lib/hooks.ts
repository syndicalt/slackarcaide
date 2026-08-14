"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiGet, wsUrl } from "@/lib/api";
import { WsClient } from "@/lib/ws";
import { errMsg } from "@/lib/errors";
import type {
  GameInfo,
  Match,
  MatchListResponse,
  Message,
  Observation,
} from "@/lib/types";

export type RealtimeStatus = "connecting" | "open" | "closed";

export function isObservation(data: unknown): data is Observation {
  return (
    !!data &&
    typeof data === "object" &&
    "match_id" in data &&
    "render" in data &&
    (data as Observation).render !== null &&
    typeof (data as Observation).render === "object"
  );
}

export function isMessage(data: unknown): data is Message {
  return (
    !!data &&
    typeof data === "object" &&
    "id" in data &&
    "content" in data &&
    "author_id" in data
  );
}

/**
 * Connect to the realtime websocket and subscribe to a set of channels.
 * The backend forwards raw payloads (observation for match:{id}, message dict
 * for messages:{channel}). Auto-reconnect re-sends the subscription.
 */
export function useRealtime(
  channels: string[],
  onRaw: (data: unknown) => void,
): RealtimeStatus {
  const [status, setStatus] = useState<RealtimeStatus>("connecting");
  const key = channels.join("|");
  const onRawRef = useRef(onRaw);

  useEffect(() => {
    onRawRef.current = onRaw;
  }, [onRaw]);

  useEffect(() => {
    const chans = key.split("|").filter(Boolean);
    const client = new WsClient(wsUrl(), {
      onOpen: (sock) => {
        setStatus("open");
        sock.send(JSON.stringify({ type: "subscribe", channels: chans }));
      },
      onMessage: (data) => onRawRef.current(data),
      onClose: () => setStatus("closed"),
      onError: () => setStatus("closed"),
    });
    return () => client.close();
  }, [key]);

  return status;
}

/**
 * Live observation for a match. Subscribes to match:{id} over WebSocket and
 * falls back to polling GET /matches/{id}/state when the socket is not open.
 */
export function useObservation(matchId: string) {
  const [observation, setObservation] = useState<Observation | null>(null);
  const [error, setError] = useState("");
  // Coalesce high-frequency WebSocket observation updates to at most one React
  // render per animation frame. Matches are authoritative and observe at the
  // display rate anyway; re-rendering the whole page per engine tick is what
  // made realtime rendering choppy.
  const pendingRef = useRef<Observation | null>(null);
  const rafRef = useRef<number>(0);
  const statusRef = useRef<RealtimeStatus>("connecting");
  const lastRealtimeAtRef = useRef(0);
  const status = useRealtime(
    [`match:${matchId}`, `messages:${matchId}`],
    (data) => {
      if (!isObservation(data)) return;
      lastRealtimeAtRef.current = Date.now();
      pendingRef.current = data;
      if (!rafRef.current && typeof requestAnimationFrame !== "undefined") {
        rafRef.current = requestAnimationFrame(() => {
          rafRef.current = 0;
          const d = pendingRef.current;
          pendingRef.current = null;
          if (d) setObservation(d);
        });
      }
    },
  );

  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  useEffect(
    () => () => {
      if (rafRef.current && typeof cancelAnimationFrame !== "undefined")
        cancelAnimationFrame(rafRef.current);
    },
    [],
  );

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let request: AbortController | null = null;

    const fetchOnce = async () => {
      request?.abort();
      request = new AbortController();
      try {
        const data = await apiGet<Observation>(`/matches/${matchId}/state`, {
          signal: request.signal,
        });
        if (alive) {
          setObservation(data);
          setError("");
        }
      } catch (e) {
        if (alive && !request.signal.aborted) setError(errMsg(e));
      }
    };

    fetchOnce();

    const loop = async () => {
      const realtimeIsStale = Date.now() - lastRealtimeAtRef.current > 5_000;
      if (statusRef.current !== "open" || realtimeIsStale) await fetchOnce();
      if (alive) timer = setTimeout(loop, 2_000);
    };
    timer = setTimeout(loop, 1500);

    return () => {
      alive = false;
      request?.abort();
      if (timer) clearTimeout(timer);
    };
  }, [matchId]);

  return { observation, error, status };
}

/**
 * Data for the canvas lobby: the game catalog (fetched once) plus open/running
 * matches (polled on an interval). On a poll error after a successful fetch we
 * keep the last data (no flicker) and surface the error string instead.
 */
export function useCanvasData(intervalMs = 6000) {
  const [games, setGames] = useState<GameInfo[] | null>(null);
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [g, m] = await Promise.all([
        apiGet<GameInfo[]>("/games"),
        apiGet<MatchListResponse>("/matches", { query: { limit: 200 } }),
      ]);
      setGames(g ?? []);
      setMatches(m?.matches ?? []);
      setError("");
    } catch (e) {
      // Keep last successful data; only surface the error.
      setError(errMsg(e));
    }
  }, []);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const loop = async () => {
      await refresh();
      if (active) timer = setTimeout(loop, intervalMs);
    };
    void loop();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [refresh, intervalMs]);

  return { games, matches, error, refresh };
}
