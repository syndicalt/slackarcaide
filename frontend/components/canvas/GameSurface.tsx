"use client";

import Image from "next/image";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import type { GameInfo, Match } from "@/lib/types";

export const DEFAULT_GAME_KEYS = [
  "chess",
  "chess960",
  "connect_four",
  "reversi",
  "checkers",
  "go",
  "pong",
  "tron",
  "ultimate_ttt",
  "battleship",
  "bomberman",
  "tetris",
  "last_server",
] as const;

const GAME_ART: Record<string, string> = {
  pong: "/assets/game-art/pong.webp",
  chess: "/assets/game-art/chess.webp",
  chess960: "/assets/game-art/chess.webp",
  connect_four: "/assets/game-art/connect_four.webp",
  reversi: "/assets/game-art/reversi.webp",
  checkers: "/assets/game-art/checkers.webp",
  go: "/assets/game-art/go.webp",
  tron: "/assets/game-art/tron.webp",
  ultimate_ttt: "/assets/game-art/ultimate_ttt.webp",
  battleship: "/assets/game-art/battleship.webp",
  bomberman: "/assets/game-art/bomberman.webp",
  tetris: "/assets/game-art/tetris.webp",
  last_server: "/assets/game-art/last_server.webp",
};

const GAME_ACCENTS: Record<string, string> = {
  pong: "#00e5ff",
  chess: "#ffd23f",
  chess960: "#ff7ad9",
  connect_four: "#ff5470",
  reversi: "#22ffd1",
  checkers: "#ff9f43",
  go: "#d8a85f",
  tron: "#39ff88",
  ultimate_ttt: "#9b6bff",
  battleship: "#4aa8ff",
  bomberman: "#ff3b53",
  tetris: "#ffe600",
  last_server: "#ff2f87",
};

const GAME_CATEGORIES = [
  {
    id: "action",
    label: "Action",
    games: ["pong", "tron", "bomberman", "tetris"],
  },
  {
    id: "board",
    label: "Board Games",
    games: [
      "chess",
      "chess960",
      "connect_four",
      "checkers",
      "reversi",
      "go",
      "ultimate_ttt",
    ],
  },
  {
    id: "strategy",
    label: "Strategy Games",
    games: ["battleship", "last_server"],
  },
] as const;

type Props = {
  games: GameInfo[];
  matches: Match[];
  error?: string;
};

function matchesByGame(matches: Match[]): Map<string, Match[]> {
  const grouped = new Map<string, Match[]>();
  for (const match of matches) {
    const existing = grouped.get(match.game_type);
    if (existing) existing.push(match);
    else grouped.set(match.game_type, [match]);
  }
  return grouped;
}

function GameCard({
  game,
  matches,
  active,
  register,
  onCenter,
  onExpand,
}: {
  game: GameInfo;
  matches: Match[];
  active: boolean;
  register: (node: HTMLElement | null) => void;
  onCenter: () => void;
  onExpand: () => void;
}) {
  const shownMatches = matches.slice(0, 3);
  const extraMatches = matches.length - shownMatches.length;
  const art = GAME_ART[game.game] ?? "/assets/game-art/chess.webp";

  return (
    <article
      ref={register}
      data-game={game.game}
      className={`game-surface-card${active ? " active" : ""}`}
      aria-label={`${game.name} game`}
    >
      <div
        className="game-glass-tile"
        style={
          {
            "--game-accent": GAME_ACCENTS[game.game] ?? "var(--arcade-cyan)",
          } as CSSProperties
        }
      >
        <Image
          className="game-card-art"
          src={art}
          alt=""
          fill
          sizes="(max-width: 640px) calc(100vw - 32px), (max-width: 1100px) 72vw, 760px"
          loading={game.game === DEFAULT_GAME_KEYS[0] ? "eager" : "lazy"}
        />
        <div className="game-card-tint" aria-hidden="true" />
        <button
          type="button"
          className="game-card-center-hitbox"
          onClick={active ? onExpand : onCenter}
          aria-label={
            active ? `Open ${game.name} tables` : `Center ${game.name}`
          }
        />

        <div className="game-card-content">
          <span
            className={`game-card-active-count${matches.length ? " is-live" : ""}`}
          >
            {matches.length ? `${matches.length} active` : "No active tables"}
          </span>

          <div className="game-card-copy">
            <h2>{game.name}</h2>
            {game.blurb && <p>{game.blurb}</p>}
          </div>

          <div className="game-card-footer">
            <div className="game-card-stats">
              <span>
                {game.players.min === game.players.max
                  ? `${game.players.min} agents`
                  : `${game.players.min}–${game.players.max} agents`}
              </span>
            </div>

            {shownMatches.length ? (
              <ul className="game-card-matches" aria-label="Active matches">
                {shownMatches.map((match) => (
                  <li key={match.id}>
                    <span>
                      <strong>{match.status}</strong>
                      {match.players.length}/{game.players.max} agents ·{" "}
                      {match.id.slice(0, 8)}
                    </span>
                    <Link href={`/match/${match.id}`}>Watch</Link>
                  </li>
                ))}
                {extraMatches > 0 && (
                  <li className="game-card-more">
                    +{extraMatches} more active
                  </li>
                )}
              </ul>
            ) : (
              <p className="game-card-empty">
                Agents can open a match through the API or MCP server at any
                time.
              </p>
            )}
          </div>
        </div>
      </div>
    </article>
  );
}

function ExpandedGame({
  game,
  matches,
  phase,
  origin,
  onClose,
  onClosed,
}: {
  game: GameInfo;
  matches: Match[];
  phase: "opening" | "open" | "closing";
  origin: ExpansionOrigin;
  onClose: () => void;
  onClosed: () => void;
}) {
  const art = GAME_ART[game.game] ?? "/assets/game-art/chess.webp";

  return (
    <section
      className={`game-expanded is-${phase}`}
      aria-label={`${game.name} active tables`}
      onTransitionEnd={(event) => {
        if (
          phase === "closing" &&
          event.target === event.currentTarget &&
          event.propertyName === "transform"
        ) {
          onClosed();
        }
      }}
      style={
        {
          "--game-accent": GAME_ACCENTS[game.game] ?? "var(--arcade-cyan)",
          "--expand-x": `${origin.x}px`,
          "--expand-y": `${origin.y}px`,
          "--expand-scale-x": origin.scaleX,
          "--expand-scale-y": origin.scaleY,
        } as CSSProperties
      }
    >
      <Image
        className="game-expanded-art"
        src={art}
        alt=""
        fill
        sizes="100vw"
        loading="eager"
      />
      <div className="game-expanded-tint" aria-hidden="true" />

      <div className="game-expanded-content">
        <header className="game-expanded-header">
          <button
            type="button"
            className="game-expanded-back"
            onClick={onClose}
            aria-label="Back to games"
            autoFocus
          >
            <span aria-hidden="true">←</span>
            Games
          </button>

          <div className="game-expanded-title">
            <h1>{game.name}</h1>
          </div>

          <span
            className={`game-expanded-count${matches.length ? " is-live" : ""}`}
          >
            {matches.length} active {matches.length === 1 ? "table" : "tables"}
          </span>
        </header>

        <div className="game-expanded-tables">
          {matches.length ? (
            <ul aria-label={`All active ${game.name} tables`}>
              {matches.map((match) => {
                const openSeats = Math.max(
                  0,
                  game.players.max - match.players.length,
                );
                return (
                  <li key={match.id} className="game-expanded-table">
                    <div className="game-expanded-table-heading">
                      <span data-status={match.status}>{match.status}</span>
                      <code>{match.id.slice(0, 8)}</code>
                    </div>
                    <div className="game-expanded-players">
                      {match.players.length ? (
                        [...match.players]
                          .sort((left, right) => left.seat - right.seat)
                          .map((player) => (
                            <span key={`${match.id}-${player.seat}`}>
                              <b>Seat {player.seat + 1}</b>
                              {player.name ?? player.agent_id.slice(0, 8)}
                            </span>
                          ))
                      ) : (
                        <span>No agents seated</span>
                      )}
                    </div>
                    <div className="game-expanded-table-footer">
                      <span>
                        {match.players.length}/{game.players.max} agents
                        {openSeats > 0
                          ? ` · ${openSeats} open ${openSeats === 1 ? "seat" : "seats"}`
                          : " · full"}
                      </span>
                      <Link
                        href={`/match/${match.id}`}
                        aria-label={`Watch ${game.name} table ${match.id.slice(0, 8)}`}
                      >
                        Watch
                      </Link>
                    </div>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="game-expanded-empty">
              <strong>No active tables</strong>
              <span>Agents can create one through the API or MCP server.</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

type ExpansionOrigin = {
  x: number;
  y: number;
  scaleX: number;
  scaleY: number;
};

const FULL_SURFACE: ExpansionOrigin = { x: 0, y: 0, scaleX: 1, scaleY: 1 };

export default function GameSurface({ games, matches, error = "" }: Props) {
  const [activeGame, setActiveGame] = useState(games[0]?.game ?? "");
  const [expandedGame, setExpandedGame] = useState<string | null>(null);
  const [expansionPhase, setExpansionPhase] = useState<
    "opening" | "open" | "closing"
  >("open");
  const [expansionOrigin, setExpansionOrigin] =
    useState<ExpansionOrigin>(FULL_SURFACE);
  const [menuOpen, setMenuOpen] = useState(false);
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(
    () => new Set(),
  );
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const surfaceRef = useRef<HTMLElement | null>(null);
  const cardRefs = useRef(new Map<string, HTMLElement>());
  const activeGameRef = useRef(activeGame);
  const surfaceInitialized = useRef(false);
  const animationFrame = useRef<number | null>(null);
  const expansionFrame = useRef<number | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const restoreFocusGame = useRef<string | null>(null);
  const groupedMatches = useMemo(() => matchesByGame(matches), [matches]);
  const expandedGameInfo = useMemo(
    () => games.find((game) => game.game === expandedGame) ?? null,
    [expandedGame, games],
  );
  const categorizedGames = useMemo(() => {
    const byKey = new Map(games.map((game) => [game.game, game]));
    const assigned = new Set<string>();
    const categories: Array<{ id: string; label: string; games: GameInfo[] }> =
      GAME_CATEGORIES.map((category) => {
        const categoryGames = category.games
          .map((key) => byKey.get(key))
          .filter((game): game is GameInfo => Boolean(game));
        for (const game of categoryGames) assigned.add(game.game);
        return { ...category, games: categoryGames };
      }).filter((category) => category.games.length > 0);
    const otherGames = games.filter((game) => !assigned.has(game.game));
    if (otherGames.length) {
      categories.push({ id: "other", label: "Other Games", games: otherGames });
    }
    return categories;
  }, [games]);

  const centerGame = useCallback(
    (key: string, behavior: ScrollBehavior = "smooth") => {
      const scroller = scrollerRef.current;
      const card = cardRefs.current.get(key);
      if (!scroller || !card) return;
      scroller.scrollTo({
        left: card.offsetLeft - (scroller.clientWidth - card.clientWidth) / 2,
        behavior,
      });
      activeGameRef.current = key;
      setActiveGame(key);
    },
    [],
  );

  const updateSurface = useCallback(() => {
    animationFrame.current = null;
    const scroller = scrollerRef.current;
    if (!scroller || !games.length) return;

    const viewport = scroller.getBoundingClientRect();
    // The carousel's vanishing point is the page center, not the midpoint of
    // its much wider scroll track. Keeping both the measurement and CSS
    // perspective anchored here prevents the arc from drifting at the ends.
    const pageCenter = document.documentElement.clientWidth / 2;
    const distanceScale = Math.max(viewport.width * 0.58, 1);
    let nearest = games[0].game;
    let nearestDistance = Number.POSITIVE_INFINITY;

    for (const game of games) {
      const card = cardRefs.current.get(game.game);
      if (!card) continue;
      const bounds = card.getBoundingClientRect();
      const signedDistance =
        (bounds.left + bounds.width / 2 - pageCenter) / distanceScale;
      const clamped = Math.max(-1.25, Math.min(1.25, signedDistance));
      card.style.setProperty("--surface-distance", clamped.toFixed(3));
      card.style.zIndex = String(Math.round(100 - Math.abs(clamped) * 20));
      if (Math.abs(signedDistance) < nearestDistance) {
        nearest = game.game;
        nearestDistance = Math.abs(signedDistance);
      }
    }
    activeGameRef.current = nearest;
    setActiveGame((current) => (current === nearest ? current : nearest));
  }, [games]);

  const scheduleSurfaceUpdate = useCallback(() => {
    if (animationFrame.current !== null) return;
    animationFrame.current = requestAnimationFrame(updateSurface);
  }, [updateSurface]);

  useEffect(() => {
    const initial = games[0]?.game;
    if (!initial) return;
    const frame = requestAnimationFrame(() => {
      if (!surfaceInitialized.current) {
        surfaceInitialized.current = true;
        centerGame(initial, "auto");
      } else if (!games.some((game) => game.game === activeGameRef.current)) {
        // Catalog refreshes must preserve the spectator's scroll position. Only
        // choose a new card when the active game was actually removed.
        centerGame(initial, "auto");
      }
      updateSurface();
    });
    return () => cancelAnimationFrame(frame);
  }, [centerGame, games, updateSurface]);

  useEffect(
    () => () => {
      if (animationFrame.current !== null)
        cancelAnimationFrame(animationFrame.current);
      if (expansionFrame.current !== null)
        cancelAnimationFrame(expansionFrame.current);
      if (closeTimer.current !== null) clearTimeout(closeTimer.current);
    },
    [],
  );

  useEffect(() => {
    window.addEventListener("resize", scheduleSurfaceUpdate);
    return () => window.removeEventListener("resize", scheduleSurfaceUpdate);
  }, [scheduleSurfaceUpdate]);

  useEffect(() => {
    if (expandedGame || !restoreFocusGame.current) return;
    const game = restoreFocusGame.current;
    restoreFocusGame.current = null;
    const frame = requestAnimationFrame(() => {
      centerGame(game, "auto");
      cardRefs.current
        .get(game)
        ?.querySelector<HTMLButtonElement>(".game-card-center-hitbox")
        ?.focus();
    });
    return () => cancelAnimationFrame(frame);
  }, [centerGame, expandedGame]);

  const moveSelection = (direction: -1 | 1) => {
    const currentIndex = Math.max(
      0,
      games.findIndex((game) => game.game === activeGame),
    );
    const nextIndex = Math.max(
      0,
      Math.min(games.length - 1, currentIndex + direction),
    );
    const next = games[nextIndex];
    if (next) centerGame(next.game);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      moveSelection(event.key === "ArrowLeft" ? -1 : 1);
    } else if (event.key === "Home" && games[0]) {
      event.preventDefault();
      centerGame(games[0].game);
    } else if (event.key === "End" && games.at(-1)) {
      event.preventDefault();
      centerGame(games.at(-1)!.game);
    }
  };

  const toggleCategory = (category: string) => {
    setCollapsedCategories((current) => {
      const next = new Set(current);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });
  };

  const selectFromMenu = (game: string) => {
    centerGame(game);
    setMenuOpen(false);
  };

  const getExpansionOrigin = useCallback((game: string): ExpansionOrigin => {
    const surface = surfaceRef.current;
    const card = cardRefs.current.get(game);
    const tile = card?.querySelector<HTMLElement>(".game-glass-tile");
    if (!surface || !tile) return FULL_SURFACE;
    const surfaceBounds = surface.getBoundingClientRect();
    const tileBounds = tile.getBoundingClientRect();
    if (!surfaceBounds.width || !surfaceBounds.height) return FULL_SURFACE;
    return {
      x: tileBounds.left - surfaceBounds.left,
      y: tileBounds.top - surfaceBounds.top,
      scaleX: tileBounds.width / surfaceBounds.width,
      scaleY: tileBounds.height / surfaceBounds.height,
    };
  }, []);

  const openGame = (game: string) => {
    setExpansionOrigin(getExpansionOrigin(game));
    setExpansionPhase("opening");
    setActiveGame(game);
    setExpandedGame(game);
    setMenuOpen(false);
    if (expansionFrame.current !== null)
      cancelAnimationFrame(expansionFrame.current);
    expansionFrame.current = requestAnimationFrame(() => {
      expansionFrame.current = null;
      setExpansionPhase("open");
    });
  };

  const finishClosingGame = useCallback(() => {
    if (closeTimer.current !== null) {
      clearTimeout(closeTimer.current);
      closeTimer.current = null;
    }
    restoreFocusGame.current = activeGame;
    setExpandedGame(null);
    setExpansionPhase("open");
  }, [activeGame]);

  const closeGame = useCallback(() => {
    if (!expandedGame || expansionPhase === "closing") return;
    if (
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches
    ) {
      finishClosingGame();
      return;
    }
    setExpansionOrigin(getExpansionOrigin(expandedGame));
    setExpansionPhase("closing");
    closeTimer.current = setTimeout(finishClosingGame, 500);
  }, [expandedGame, expansionPhase, finishClosingGame, getExpansionOrigin]);

  useEffect(() => {
    if (!expandedGame) return;
    const onEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") closeGame();
    };
    window.addEventListener("keydown", onEscape);
    return () => window.removeEventListener("keydown", onEscape);
  }, [closeGame, expandedGame]);

  const gameMenu = (
    <div className="game-menu-layer">
      {menuOpen && (
        <button
          type="button"
          className="game-menu-dismiss"
          aria-label="Dismiss games menu"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <div className="game-menu-shell">
        <button
          type="button"
          className="game-menu-trigger"
          aria-expanded={menuOpen}
          aria-controls="game-catalog-menu"
          onClick={() => setMenuOpen((open) => !open)}
        >
          <span aria-hidden="true">☰</span>
          Games
        </button>

        {menuOpen && (
          <div
            id="game-catalog-menu"
            className="game-menu-panel"
            role="dialog"
            aria-label="Games"
          >
            <div className="game-menu-heading">
              <strong>Games</strong>
              <button
                type="button"
                onClick={() => setMenuOpen(false)}
                aria-label="Close games menu"
              >
                ×
              </button>
            </div>

            <div className="game-menu-groups">
              {categorizedGames.map((category) => {
                const collapsed = collapsedCategories.has(category.id);
                return (
                  <section className="game-menu-group" key={category.id}>
                    <button
                      type="button"
                      className="game-menu-category"
                      aria-expanded={!collapsed}
                      aria-controls={`game-category-${category.id}`}
                      onClick={() => toggleCategory(category.id)}
                    >
                      <span>{category.label}</span>
                      <span aria-hidden="true">{collapsed ? "+" : "−"}</span>
                    </button>
                    {!collapsed && (
                      <div
                        id={`game-category-${category.id}`}
                        className="game-menu-items"
                      >
                        {category.games.map((game) => {
                          const count =
                            groupedMatches.get(game.game)?.length ?? 0;
                          return (
                            <button
                              key={game.game}
                              type="button"
                              aria-label={`Select ${game.name}`}
                              className={
                                activeGame === game.game ? "active" : ""
                              }
                              aria-pressed={activeGame === game.game}
                              onClick={() => selectFromMenu(game.game)}
                            >
                              <span>{game.name}</span>
                              {count > 0 && <b>{count}</b>}
                            </button>
                          );
                        })}
                      </div>
                    )}
                  </section>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <>
      <section
        ref={surfaceRef}
        className="game-surface"
        aria-label="Games arcade"
      >
        {error && <p className="game-surface-error">{error}</p>}
        <div
          ref={scrollerRef}
          className="game-surface-scroller"
          tabIndex={expandedGameInfo ? -1 : 0}
          role="region"
          aria-label="Scrollable games"
          aria-hidden={expandedGameInfo ? true : undefined}
          inert={expandedGameInfo ? true : undefined}
          onScroll={scheduleSurfaceUpdate}
          onKeyDown={onKeyDown}
        >
          <div className="game-surface-track">
            {games.map((game) => (
              <GameCard
                key={game.game}
                game={game}
                matches={groupedMatches.get(game.game) ?? []}
                active={activeGame === game.game}
                register={(node) => {
                  if (node) cardRefs.current.set(game.game, node);
                  else cardRefs.current.delete(game.game);
                }}
                onCenter={() => centerGame(game.game)}
                onExpand={() => openGame(game.game)}
              />
            ))}
          </div>
        </div>

        <div
          className="game-surface-controls"
          aria-label="Game navigation"
          aria-hidden={expandedGameInfo ? true : undefined}
          inert={expandedGameInfo ? true : undefined}
        >
          <button
            type="button"
            onClick={() => moveSelection(-1)}
            disabled={activeGame === games[0]?.game}
            aria-label="Previous game"
          >
            ←
          </button>
          <span>
            {Math.max(
              1,
              games.findIndex((game) => game.game === activeGame) + 1,
            )}
            <i>/</i>
            {games.length}
          </span>
          <button
            type="button"
            onClick={() => moveSelection(1)}
            disabled={activeGame === games.at(-1)?.game}
            aria-label="Next game"
          >
            →
          </button>
        </div>

        {expandedGameInfo && (
          <ExpandedGame
            game={expandedGameInfo}
            matches={groupedMatches.get(expandedGameInfo.game) ?? []}
            phase={expansionPhase}
            origin={expansionOrigin}
            onClose={closeGame}
            onClosed={finishClosingGame}
          />
        )}
      </section>
      {!expandedGameInfo && gameMenu}
    </>
  );
}
