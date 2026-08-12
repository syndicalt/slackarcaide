// Human-readable + flattening helpers for machine-form legal actions.

export function describeAction(a: unknown): string {
  if (a && typeof a === "object" && !Array.isArray(a)) {
    const entries = Object.entries(a as Record<string, unknown>);
    if (entries.length === 0) return "noop";
    const parts = entries.map(([k, v]) => {
      const vs = typeof v === "object" ? JSON.stringify(v) : String(v);
      return `${k}=${vs}`;
    });
    return parts.join(" ");
  }
  return String(a);
}

/** Flatten per-seat nested legal actions into a deduped list of action dicts. */
export function flattenActions(legalActions?: unknown[]): unknown[] {
  if (!legalActions || legalActions.length === 0) return [];
  const out: unknown[] = [];
  const seen = new Set<string>();
  const push = (a: unknown) => {
    const key = JSON.stringify(a);
    if (seen.has(key)) return;
    seen.add(key);
    out.push(a);
  };
  for (const entry of legalActions) {
    if (Array.isArray(entry)) {
      for (const a of entry) push(a);
    } else {
      push(entry);
    }
  }
  return out;
}
