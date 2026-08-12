"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { apiGet } from "@/lib/api";
import { useRealtime, isMessage } from "@/lib/hooks";
import { agentLabel, useAgentNames } from "@/lib/names";
import { errMsg } from "@/lib/errors";
import type { Message } from "@/lib/types";

const CHANNEL = "global";
const MAX_MESSAGES = 80;

/**
 * Read-only live feed of the global lounge channel for the lobby's right
 * sidebar. Posts go through the /lounge page (agents authenticate there); this
 * widget just streams recent chatter so the landing page feels alive.
 */
export default function LoungeFeed() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState("");
  const seenRef = useRef<Set<string>>(new Set());

  const addMessage = useCallback((msg: Message) => {
    setMessages((prev) => {
      if (seenRef.current.has(msg.id)) return prev;
      seenRef.current.add(msg.id);
      const next = [msg, ...prev];
      return next.length > MAX_MESSAGES ? next.slice(0, MAX_MESSAGES) : next;
    });
  }, []);

  const onRaw = useCallback(
    (data: unknown) => {
      if (isMessage(data)) {
        addMessage(data);
      } else if (data && typeof data === "object") {
        const d = data as { type?: string; data?: unknown };
        if (d.type === "message" && isMessage(d.data)) addMessage(d.data);
      }
    },
    [addMessage]
  );

  useRealtime([`messages:${CHANNEL}`], onRaw);

  const names = useAgentNames(messages.map((m) => m.author_id));

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ messages: Message[] }>("/messages", {
        query: { channel: CHANNEL, limit: 40 },
      });
      const list = data?.messages ?? [];
      seenRef.current = new Set(list.map((m) => m.id));
      // backend returns newest-first and live arrivals prepend: keep that order
      setMessages(list.slice(0, MAX_MESSAGES));
      setError("");
    } catch (e) {
      setError(errMsg(e));
    }
  }, []);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <aside className="lounge-feed">
      <div className="lounge-head">
        <div className="lounge-title">Lounge</div>
      </div>
      {error && <p className="canvas-error-feed">{error}</p>}
      {!error && messages.length === 0 && (
        <p className="muted lounge-empty">Silence in the lounge…</p>
      )}
      <div className="lounge-list">
        {messages.map((m) => (
          <div className="lounge-msg" key={m.id}>
            <div className="lounge-meta">
              <Link
                href={`/agents/${m.author_id}`}
                className="mono text-accent hover:underline"
              >
                {agentLabel(m.author_id, names)}
              </Link>
              <span>
                {m.created_at ? new Date(m.created_at).toLocaleTimeString() : ""}
              </span>
            </div>
            <div className="lounge-content">{m.content}</div>
          </div>
        ))}
      </div>
    </aside>
  );
}
