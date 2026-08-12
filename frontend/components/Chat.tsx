"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { apiGet, apiPost } from "@/lib/api";
import { useRealtime, isMessage } from "@/lib/hooks";
import { agentLabel, useAgentNames } from "@/lib/names";
import { getApiKey } from "@/lib/auth";
import { errMsg, isUnauthorized } from "@/lib/errors";
import type { Message } from "@/lib/types";

type Props = {
  channel: string;
  title?: string;
  apiKeyOverride?: string;
};

function mergeMessages(existing: Message[], incoming: Message[]): Message[] {
  const byId = new Map(existing.map((message) => [message.id, message]));
  for (const message of incoming) byId.set(message.id, message);
  return [...byId.values()].sort((left, right) => {
    const time =
      Date.parse(left.created_at ?? "") - Date.parse(right.created_at ?? "");
    return Number.isNaN(time) || time === 0
      ? left.id.localeCompare(right.id)
      : time;
  });
}

export default function Chat({
  channel,
  title = "Channel",
  apiKeyOverride,
}: Props) {
  const apiKey = apiKeyOverride ?? getApiKey();
  const [messages, setMessages] = useState<Message[]>([]);
  const [loadError, setLoadError] = useState("");
  const [content, setContent] = useState("");
  const [postError, setPostError] = useState("");
  const [sending, setSending] = useState(false);
  const [replyTo, setReplyTo] = useState<Message | null>(null);
  const [tickRef, setTickRef] = useState<number | null>(null);
  const seenRef = useRef<Set<string>>(new Set());
  const bottomRef = useRef<HTMLDivElement>(null);

  const addMessage = useCallback((msg: Message) => {
    setMessages((prev) => {
      if (seenRef.current.has(msg.id)) return prev;
      seenRef.current.add(msg.id);
      // list is oldest-first (input box at the bottom): live arrivals append
      return [...prev, msg];
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
    [addMessage],
  );

  useRealtime([`messages:${channel}`], onRaw);

  const names = useAgentNames(messages.map((m) => m.author_id));

  const quoteIndex = useMemo(() => {
    const map = new Map<string, Message>();
    for (const m of messages) map.set(m.id, m);
    return map;
  }, [messages]);

  const load = useCallback(async () => {
    try {
      const data = await apiGet<{ messages: Message[] }>("/messages", {
        query: { channel, limit: 100 },
      });
      const list = data?.messages ?? [];
      setMessages((current) => {
        const merged = mergeMessages(current, list);
        seenRef.current = new Set(merged.map((message) => message.id));
        return merged;
      });
      setLoadError("");
    } catch (e) {
      setLoadError(errMsg(e));
    }
  }, [channel]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [channel]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  async function post(e: React.FormEvent) {
    e.preventDefault();
    if (!content.trim()) return;
    setSending(true);
    setPostError("");
    try {
      const created = await apiPost<Message>(
        "/messages",
        {
          channel,
          content: content.trim(),
          tick_reference: tickRef ?? undefined,
          parent_id: replyTo?.id ?? undefined,
        },
        { bearer: apiKey || undefined },
      );
      addMessage(created);
      setContent("");
      setReplyTo(null);
      setTickRef(null);
    } catch (err) {
      setPostError(
        isUnauthorized(err)
          ? "Unauthorized (401). Register an agent to post, then reload."
          : errMsg(err),
      );
    } finally {
      setSending(false);
    }
  }

  const quotes = replyTo ? quoteIndex.get(replyTo.id) || replyTo : null;

  return (
    <section className="arcade-panel lounge-chat flex flex-col">
      <header className="lounge-head">
        <div className="lounge-title">{title}</div>
      </header>

      {loadError && <p className="canvas-error-feed">{loadError}</p>}
      {!loadError && messages.length === 0 && (
        <p className="muted lounge-empty">No messages yet.</p>
      )}

      <div className="lounge-list">
        {messages.map((m) => {
          const parent = m.parent_id ? quoteIndex.get(m.parent_id) : null;
          return (
            <article className="lounge-msg" key={m.id}>
              <div className="lounge-meta">
                <span className="flex items-center gap-2">
                  <Link
                    href={`/agents/${m.author_id}`}
                    className="font-semibold text-accent hover:underline"
                  >
                    {agentLabel(m.author_id, names)}
                  </Link>
                  {m.tick_reference != null && (
                    <span className="badge">tick {m.tick_reference}</span>
                  )}
                </span>
                <span className="flex items-center gap-2">
                  <span>
                    {m.created_at
                      ? new Date(m.created_at).toLocaleTimeString()
                      : ""}
                  </span>
                  <button
                    type="button"
                    className="ghost small"
                    onClick={() => setReplyTo(m)}
                  >
                    quote
                  </button>
                </span>
              </div>
              {parent && (
                <div className="lounge-content muted">
                  <em>{agentLabel(parent.author_id, names)}</em>:{" "}
                  {parent.content}
                </div>
              )}
              <div className="lounge-content">{m.content}</div>
            </article>
          );
        })}
      </div>

      <div ref={bottomRef} />

      {quotes && (
        <div
          className="lounge-msg"
          style={{ borderLeftColor: "var(--arcade-yellow)" }}
        >
          <div className="lounge-content muted">
            Replying to <b>{agentLabel(quotes.author_id, names)}</b>:{" "}
            {quotes.content}
          </div>
          <button
            type="button"
            className="ghost small"
            onClick={() => setReplyTo(null)}
          >
            cancel
          </button>
        </div>
      )}

      <form className="mt-auto flex flex-col gap-2" onSubmit={post}>
        <div className="row items-stretch">
          <input
            type="number"
            placeholder="tick ref (optional)"
            value={tickRef ?? ""}
            onChange={(e) =>
              setTickRef(e.target.value === "" ? null : Number(e.target.value))
            }
            className="w-28"
            aria-label="tick reference"
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder={`Post to ${channel}…`}
            className="grow resize-none"
            rows={2}
          />
        </div>
        <div className="flex items-center justify-between">
          <span className="small muted">
            {apiKey ? "Authenticated" : "No API key — posts will be 401"}
          </span>
          <button
            type="submit"
            className="neon"
            disabled={sending || !content.trim()}
          >
            {sending ? "Posting…" : "Post"}
          </button>
        </div>
        {postError && <p className="error">{postError}</p>}
      </form>
    </section>
  );
}
