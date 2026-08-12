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
  onRaw: (data: unknown) => void
): RealtimeStatus {
  const [status, setStatus] = useState<RealtimeStatus>("connecting");
  const key = channels.join("|");
  const onRawRef = useRef(onRaw);
  onRawRef.current = onRaw;

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
  statusRef.current = useRealtime(
    [`match:${matchId}`, `messages:${matchId}`],
    (data) => {
      if (!isObservation(data)) return;
      pendingRef.current = data;
      if (!rafRef.current && typeof requestAnimationFrame !== "undefined") {
        rafRef.current = requestAnimationFrame(() => {
          rafRef.current = 0;
          const d = pendingRef.current;
          pendingRef.current = null;
          if (d) setObservation(d);
        });
      }
    }
  );

  useEffect(
    () => () => {
      if (rafRef.current && typeof cancelAnimationFrame !== "undefined")
        cancelAnimationFrame(rafRef.current);
    },
    []
  );

  useEffect(() => {
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const fetchOnce = async () => {
      try {
        const data = await apiGet<Observation>(`/matches/${matchId}/state`);
        if (alive) {
          setObservation(data);
          setError("");
        }
      } catch (e) {
        if (alive) setError(errMsg(e));
      }
    };

    fetchOnce();

    const loop = async () => {
      if (statusRef.current !== "open") await fetchOnce();
      if (alive) timer = setTimeout(loop, 1500);
    };
    timer = setTimeout(loop, 1500);

    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [matchId]);

  return { observation, error, status: statusRef.current };
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
        apiGet<MatchListResponse>("/matches"),
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
    refresh();
    const timer = setInterval(refresh, intervalMs);
    return () => clearInterval(timer);
  }, [refresh, intervalMs]);

  return { games, matches, error, refresh };
}
