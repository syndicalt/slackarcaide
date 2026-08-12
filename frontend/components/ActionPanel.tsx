"use client";

import { describeAction, flattenActions } from "@/lib/actions";

export default function ActionPanel({
  legalActions,
  onSubmit,
  disabled = false,
  active = false,
}: {
  legalActions: unknown[];
  onSubmit: (action: unknown) => void;
  disabled?: boolean;
  active?: boolean; // highlight when it is this player's turn to act
}) {
  const actions = flattenActions(legalActions);
  if (actions.length === 0) {
    return (
      <div className="muted small">
        {active ? "Your turn — no legal actions available." : "No legal actions available right now."}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {actions.map((a, i) => (
        <button
          key={i}
          type="button"
          className={active ? "neon" : "ghost"}
          disabled={disabled}
          onClick={() => onSubmit(a)}
        >
          {describeAction(a)}
        </button>
      ))}
    </div>
  );
}
