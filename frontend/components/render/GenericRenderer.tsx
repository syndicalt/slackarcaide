"use client";

import { useState } from "react";
import type { RenderData } from "@/lib/types";

function renderValue(value: unknown, depth: number): string {
  const pad = "  ".repeat(depth);
  if (value === null || value === undefined) return `${pad}null`;
  if (typeof value === "string") return `${pad}"${value}"`;
  if (typeof value === "number" || typeof value === "boolean") return `${pad}${String(value)}`;
  if (Array.isArray(value)) {
    if (value.length === 0) return `${pad}[]`;
    const head = value[0];
    if (head === null || typeof head !== "object") {
      return `${pad}[${value.map((v) => renderValue(v, 0).trim()).join(", ")}]`;
    }
    const items = value
      .map((v, i) => {
        const inner = renderValue(v, depth + 1).slice(depth * 2 + 2);
        return `${pad}  [${i}]: ${inner}`;
      })
      .join("\n");
    return `${pad}[\n${items}\n${pad}]`;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return `${pad}{}`;
    const items = entries
      .map(([k, v]) => `${pad}  ${k}: ${renderValue(v, depth + 1).slice(depth * 2 + 2)}`)
      .join("\n");
    return `${pad}{\n${items}\n${pad}}`;
  }
  return `${pad}${String(value)}`;
}

/**
 * Generic fallback renderer — draws any game's render data as a structured
 * listing. The match page renders legal actions alongside via <ActionPanel>,
 * so even games without a dedicated canvas are fully observable + controllable.
 */
export default function GenericRenderer({ render }: { render: RenderData }) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="rounded-lg border border-edge bg-[#06080d] p-4 font-mono text-sm">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-muted">Generic engine render — raw JSON state</span>
        <button
          type="button"
          className="ghost small"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Collapse" : "Expand"}
        </button>
      </div>
      {expanded && (
        <pre className="muted overflow-auto max-h-[60vh] whitespace-pre-wrap">
          {renderValue(render, 0)}
        </pre>
      )}
    </div>
  );
}
