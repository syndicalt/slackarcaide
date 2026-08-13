// Shared API + domain types for Agent Arcade.
// Shapes mirror the backend (FastAPI) responses exactly (see backend/app/api/*).

// ---------------------------------------------------------------------------
// Auth / agents
// ---------------------------------------------------------------------------

export type AgentPublic = {
  id: string;
  display_name: string;
  bio?: string | null;
  avatar_url?: string | null;
  created_at?: string | null;
  stats?: Record<string, unknown>;
};

export type AgentRating = {
  game: string;
  elo: number;
  provisional: boolean;
  games_played: number;
  wins: number;
  losses: number;
  draws: number;
  last_change: number;
};

// ---------------------------------------------------------------------------
// Games catalog
// ---------------------------------------------------------------------------

export type GameInfo = {
  game: string;
  mode: "realtime" | "turnbased";
  name: string;
  players: { min: number; max: number };
  players_before_start: number;
  elo_ranked: boolean;
  blurb: string;
};

// ---------------------------------------------------------------------------
// Matches
// ---------------------------------------------------------------------------

export type MatchPlayer = {
  agent_id: string;
  seat: number;
  side?: string | null;
  name?: string | null; // display_name snapshot captured at join time
};

export type Match = {
  id: string;
  game_type: string;
  mode: string;
  status: string;
  config?: Record<string, unknown>;
  seed?: number;
  players: MatchPlayer[];
  result?: Record<string, unknown> | null;
  started_at?: string | null;
  ended_at?: string | null;
  tick_or_move_count?: number;
  created_at?: string | null;
};

export type MatchListResponse = { matches: Match[] };

export type HistoricalMatch = Match & {
  outcome?: "win" | "loss" | "draw" | null;
  final_summary?: string | null;
  winner_seats: number[];
  replay_url: string;
};

export type MatchHistoryResponse = {
  matches: HistoricalMatch[];
  next_cursor?: string | null;
};

// ---------------------------------------------------------------------------
// Shared spectator observation returned by the match manager.
// ---------------------------------------------------------------------------

export type Observation = {
  match_id: string;
  game: string;
  mode: "realtime" | "turnbased";
  tick: number;
  status: string;
  players: MatchPlayer[];
  your_player_id?: string | null;
  state: Record<string, unknown>;
  legal_actions: unknown[];
  scores: Record<string, unknown>;
  summary?: string;
  last_move?: unknown;
  time?: unknown;
  /** get_render_data() — the authoritative keys the canvas renderers read. */
  render: RenderData;
};

export type RenderData = Record<string, unknown>;

// ---------------------------------------------------------------------------
// Replay
// ---------------------------------------------------------------------------

export type ReplayFrame = {
  tick: number;
  render: RenderData;
  summary?: string;
  seat?: number | null;
  agent?: string | null;
  intent?: string | null;
  terminal?: boolean;
  terminal_reason?: string;
  kind?: "initial" | "action" | "terminal";
};

export type ReplayResponse = {
  match_id: string;
  game: string;
  mode: string;
  seed?: number;
  players: MatchPlayer[];
  result?: Record<string, unknown> | null;
  tick_or_move_count?: number;
  frames: ReplayFrame[];
  frame_count: number;
  next_frame_offset?: number | null;
};

// ---------------------------------------------------------------------------
// Leaderboards
// ---------------------------------------------------------------------------

export type LeaderboardEntry = {
  rank: number;
  agent_id: string;
  display_name?: string | null;
  elo: number;
  provisional: boolean;
  games_played: number;
  wins: number;
  losses: number;
  draws: number;
  last_change: number;
};

export type LeaderboardResponse = {
  game: string;
  count: number;
  entries: LeaderboardEntry[];
};

// ---------------------------------------------------------------------------
// Messages
// ---------------------------------------------------------------------------

export type Message = {
  id: string;
  channel: string;
  author_id: string;
  content: string;
  tick_reference?: number | null;
  parent_id?: string | null;
  created_at?: string | null;
};

export type MessageListResponse = { messages: Message[] };

// ---------------------------------------------------------------------------
// Realtime envelope — payloads published on match:{id} / messages:{channel}
// ---------------------------------------------------------------------------

export type RealtimeEnvelope =
  | { type: "message"; channel: string; data: Message }
  | { type: "pong" }
  | { type: string; [k: string]: unknown };

// ---------------------------------------------------------------------------
// Per-game render data (from each game engine's get_render_data()).
// Renderers read these keys off Observation.render / ReplayFrame.render.
// ---------------------------------------------------------------------------

export type RenderPong = {
  w: number;
  h: number;
  paddle_w: number;
  paddle_h: number;
  paddles: [number, number]; // TOP-EDGE y of paddle 0 / 1 (not center)
  ball: { x: number; y: number; r: number };
  serve_in?: number; // ticks the ball stays parked at center after a score
  scores: [number, number];
};

export type RenderChess = {
  fen: string;
  turn: number;
  legal_count: number;
  chess960_position?: number | null;
  last_move?: unknown;
};
