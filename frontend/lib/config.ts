/**
 * Lobby focus list. Only these games are live in the canvas scene — every other
 * game renders as a disabled cabinet (dimmed, non-interactive) until its key is
 * added here. Lets us harden one game at a time without deleting the others.
 */
export const FOCUS_GAMES: readonly string[] = ["pong", "chess"];
