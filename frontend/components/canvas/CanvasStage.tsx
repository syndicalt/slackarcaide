"use client";

import { useEffect, useRef, useState } from "react";
import {
  ViewContext,
  clampScale,
  LAYOUT_MIN_X,
  LAYOUT_CENTER_Y,
  VIEW_LEFT_GAP,
  type CanvasView,
} from "./view";

export default function CanvasStage({
  children,
}: {
  children: React.ReactNode;
}) {
  const [view, setView] = useState<CanvasView>(() => ({
    x: 0,
    y: 0,
    scale: 1,
  }));
  const [panning, setPanning] = useState(false);
  const viewportRef = useRef<HTMLDivElement | null>(null);
  const panRef = useRef<{
    active: boolean;
    sx: number;
    sy: number;
    vx: number;
    vy: number;
  } | null>(null);
  const panFrameRef = useRef<number | null>(null);
  const pendingPointRef = useRef<{ x: number; y: number } | null>(null);

  // Start camera: nudge the grid right of the catalog menu (col1 clear of the
  // panel), vertically centered. Runs client-side only; deterministic.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el || typeof window === "undefined") return;
    setView({
      x: VIEW_LEFT_GAP - LAYOUT_MIN_X,
      y: el.clientHeight / 2 - LAYOUT_CENTER_Y,
      scale: 1,
    });
  }, []);

  // Wheel zoom must call preventDefault, so it cannot use React's passive
  // onWheel. Attach a non-passive listener directly.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setView((v) => {
        const rect = el.getBoundingClientRect();
        const mx = e.clientX - rect.left;
        const my = e.clientY - rect.top;
        const next = clampScale(v.scale * (e.deltaY < 0 ? 1.12 : 1 / 1.12));
        const k = next / v.scale;
        return {
          scale: next,
          x: mx - (mx - v.x) * k,
          y: my - (my - v.y) * k,
        };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const onBgPointerDown = (e: React.PointerEvent) => {
    // Nodes tag themselves with [data-node] and stop their own propagation,
    // but guard anyway so a pointerdown on interactive children can't pan.
    if ((e.target as HTMLElement).closest("[data-node]")) return;
    panRef.current = {
      active: true,
      sx: e.clientX,
      sy: e.clientY,
      vx: view.x,
      vy: view.y,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
    setPanning(true);
  };

  const onBgPointerMove = (e: React.PointerEvent) => {
    const p = panRef.current;
    if (!p || !p.active) return;
    pendingPointRef.current = {
      x: p.vx + (e.clientX - p.sx),
      y: p.vy + (e.clientY - p.sy),
    };
    if (panFrameRef.current === null) {
      panFrameRef.current = requestAnimationFrame(() => {
        panFrameRef.current = null;
        const point = pendingPointRef.current;
        if (point) setView((current) => ({ ...current, ...point }));
      });
    }
  };

  const stopPan = () => {
    panRef.current = null;
    pendingPointRef.current = null;
    setPanning(false);
  };

  useEffect(
    () => () => {
      if (panFrameRef.current !== null)
        cancelAnimationFrame(panFrameRef.current);
    },
    [],
  );

  const zoomBy = (factor: number) => {
    const el = viewportRef.current;
    if (!el) return;
    setView((v) => {
      const cx = el.clientWidth / 2;
      const cy = el.clientHeight / 2;
      const next = clampScale(v.scale * factor);
      const k = next / v.scale;
      return {
        scale: next,
        x: cx - (cx - v.x) * k,
        y: cy - (cy - v.y) * k,
      };
    });
  };

  const resetView = () => {
    const el = viewportRef.current;
    if (!el) return;
    setView({
      x: VIEW_LEFT_GAP - LAYOUT_MIN_X,
      y: el.clientHeight / 2 - LAYOUT_CENTER_Y,
      scale: 1,
    });
  };

  return (
    <ViewContext.Provider value={{ scale: view.scale }}>
      <div
        ref={viewportRef}
        className={`canvas-viewport${panning ? " panning" : ""}`}
        onPointerDown={onBgPointerDown}
        onPointerMove={onBgPointerMove}
        onPointerUp={stopPan}
        onPointerCancel={stopPan}
      >
        <div
          className="canvas-layer"
          style={{
            transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})`,
            transformOrigin: "0 0",
          }}
        >
          {children}
        </div>
        <div className="canvas-zoom">
          <button
            type="button"
            className="ghost"
            onClick={() => zoomBy(1 / 1.25)}
            aria-label="Zoom out"
          >
            −
          </button>
          <button
            type="button"
            className="ghost"
            onClick={resetView}
            aria-label="Reset view"
          >
            reset
          </button>
          <button
            type="button"
            className="ghost"
            onClick={() => zoomBy(1.25)}
            aria-label="Zoom in"
          >
            +
          </button>
        </div>
      </div>
    </ViewContext.Provider>
  );
}
