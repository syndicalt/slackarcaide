"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { apiGet } from "@/lib/api";
import { errMsg } from "@/lib/errors";
import type { ReplayResponse } from "@/lib/types";
import EngineCanvas from "@/components/render/EngineCanvas";

export default function ReplayPage() {
  const { id } = useParams<{ id: string }>();
  const [replay, setReplay] = useState<ReplayResponse | null>(null);
  const [loadError, setLoadError] = useState("");
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(2); // ticks per second
  const [offset, setOffset] = useState(0);
  const [loadingPage, setLoadingPage] = useState(false);
  const timerRef = useRef<number | undefined>(undefined);

  const loadPage = useCallback(
    async (frameOffset: number, position: "start" | "end" = "start") => {
      setLoadingPage(true);
      try {
        const response = await apiGet<ReplayResponse>(`/matches/${id}/replay`, {
          query: { frame_offset: frameOffset, frame_limit: 2000 },
        });
        setReplay(response);
        setOffset(frameOffset);
        setIndex(
          position === "end" ? Math.max(0, response.frames.length - 1) : 0,
        );
        setLoadError("");
      } catch (cause) {
        setLoadError(errMsg(cause));
      } finally {
        setLoadingPage(false);
      }
    },
    [id],
  );

  useEffect(() => {
    let alive = true;
    apiGet<ReplayResponse>(`/matches/${id}/replay`, {
      query: { frame_offset: 0, frame_limit: 2000 },
    })
      .then((r) => {
        if (!alive) return;
        setReplay(r);
        setOffset(0);
        setIndex(0);
      })
      .catch((e) => alive && setLoadError(errMsg(e)));
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    clearInterval(timerRef.current);
    timerRef.current = undefined;
    if (playing && replay && replay.frames.length > 1) {
      timerRef.current = window.setInterval(() => {
        setIndex((i) => {
          if (i + 1 < replay.frames.length) return i + 1;
          setPlaying(false);
          return i;
        });
      }, 1000 / speed);
    }
    return () => clearInterval(timerRef.current);
  }, [playing, speed, replay]);

  const stop = useCallback(() => setPlaying(false), []);

  const frames = replay?.frames ?? [];
  const frame = frames[index];
  const total = frames.length;

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Link href="/" className="ghost rounded-lg border px-3 py-1.5 text-sm">
          ← Lobby
        </Link>
        <h1 className="mb-0 text-xl">Replay</h1>
        {replay && (
          <span className="badge">
            {replay.game} · {replay.mode}
          </span>
        )}
        <span className="muted small mono">/replay/{id.slice(0, 8)}</span>
        <Link
          href={`/match/${id}`}
          className="ghost rounded border px-3 py-1.5 text-sm"
        >
          Match thread
        </Link>
      </div>

      {loadError && <p className="error">{loadError}</p>}

      {!replay && !loadError && <p className="muted">Loading replay…</p>}

      {replay && total === 0 && (
        <div className="panel">
          <p className="muted">No recorded action frames for this match.</p>
        </div>
      )}

      {replay && total > 0 && frame && (
        <>
          <div className="panel neon">
            <EngineCanvas game={replay.game} render={frame.render} />
            {frame.summary && (
              <p className="muted small mt-2">{frame.summary}</p>
            )}
          </div>

          <div className="panel">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  stop();
                  setIndex((i) => Math.max(0, i - 1));
                }}
                disabled={index <= 0}
              >
                ‹ Prev
              </button>
              <button
                type="button"
                className={playing ? "" : "neon"}
                onClick={() => setPlaying((p) => !p)}
              >
                {playing ? "Pause" : "Play"}
              </button>
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  stop();
                  setIndex((i) => Math.min(total - 1, i + 1));
                }}
                disabled={index >= total - 1}
              >
                Next ›
              </button>
              <span className="muted small mono">
                frame {offset + index + 1} / {replay.frame_count} · tick{" "}
                {frame.tick} / {replay.tick_or_move_count ?? frame.tick}
              </span>
              <select
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
                className="w-28"
                aria-label="speed"
              >
                {[1, 2, 4, 8].map((s) => (
                  <option key={s} value={s}>
                    {s} tick/s
                  </option>
                ))}
              </select>
            </div>

            <input
              type="range"
              min={0}
              max={total - 1}
              value={index}
              onChange={(e) => {
                stop();
                setIndex(Number(e.target.value));
              }}
              className="w-full accent-[#7c7cff]"
              aria-label="frame seek"
            />

            <p className="muted small mt-2">
              loaded frames {offset + 1}-{offset + total} of{" "}
              {replay.frame_count} · seed {replay.seed}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                className="ghost"
                disabled={offset === 0 || loadingPage}
                onClick={() => {
                  stop();
                  void loadPage(Math.max(0, offset - 2000), "end");
                }}
              >
                Previous 2,000 frames
              </button>
              <button
                type="button"
                className="ghost"
                disabled={replay.next_frame_offset == null || loadingPage}
                onClick={() => {
                  stop();
                  if (replay.next_frame_offset != null)
                    void loadPage(replay.next_frame_offset);
                }}
              >
                Next 2,000 frames
              </button>
              {loadingPage && (
                <span className="muted small">Loading frames…</span>
              )}
            </div>
          </div>
        </>
      )}
    </section>
  );
}
