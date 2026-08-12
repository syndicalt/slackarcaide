"use client";

import type { GameInfo } from "@/lib/types";

type Props = {
  games: GameInfo[];
  /** active game key, or null for "All games" */
  active: string | null;
  onSelect: (key: string | null) => void;
  /** count of open+running matches per game key */
  openCounts: Record<string, number>;
  /** game keys that are disabled in the lobby (only FOCUS_GAMES are live) */
  disabledKeys?: ReadonlySet<string>;
  /** collapse the sidebar (hide it) */
  onClose: () => void;
};

/**
 * Right-hand lobby sidebar. Selecting a game filters which nodes show their
 * table cards on the canvas ("All games" shows every node's cards).
 */
export default function CatalogMenu({
  games,
  active,
  onSelect,
  openCounts,
  disabledKeys = new Set(),
  onClose,
}: Props) {
  const total = (games ?? []).reduce((sum, g) => sum + (openCounts[g.game] ?? 0), 0);

  return (
    <div className="catalog-menu">
      <div className="catalog-head">
        <div className="catalog-title">Games</div>
        <button
          type="button"
          className="catalog-collapse"
          onClick={onClose}
          aria-label="Hide games sidebar"
        >
          ×
        </button>
      </div>
      <button
        type="button"
        className={`catalog-row${active === null ? " active" : ""}`}
        onClick={() => onSelect(null)}
      >
        <span>All games</span>
        {total > 0 && <span className="catalog-count">{total}</span>}
      </button>
      {games.map((g) => {
        const count = openCounts[g.game] ?? 0;
        const isActive = active === g.game;
        const isDisabled = disabledKeys.has(g.game);
        return (
          <button
            key={g.game}
            type="button"
            className={`catalog-row${isActive ? " active" : ""}${isDisabled ? " disabled" : ""}`}
            onClick={() => {
              if (isDisabled) return;
              onSelect(isActive ? null : g.game);
            }}
          >
            <span>{g.name}</span>
            {!isDisabled && count > 0 && <span className="catalog-count">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}
