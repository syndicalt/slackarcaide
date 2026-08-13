"use client";

type Role = "maintainer" | "corrupted";
type MissionOutcome = "repaired" | "sabotaged" | "sabotaged_by_deadlock";

type Player = { seat: number; name: string };
type Mission = {
  round: number;
  outcome: MissionOutcome;
  team: number[];
  sabotages: number;
};

type LastServerRender = {
  phase?: unknown;
  turn?: unknown;
  coordinator?: unknown;
  round?: unknown;
  rounds_total?: unknown;
  team_size?: unknown;
  proposed_team?: unknown;
  votes_submitted?: unknown;
  mission_actions_submitted?: unknown;
  rejected_proposals?: unknown;
  players?: unknown;
  scores?: unknown;
  missions?: unknown;
  terminal?: unknown;
  winner_faction?: unknown;
  roles?: unknown;
};

const MAX_PLAYERS = 7;
const MAX_MISSIONS = 5;

function integer(value: unknown, minimum: number, maximum: number): number {
  return typeof value === "number" &&
    Number.isInteger(value) &&
    value >= minimum &&
    value <= maximum
    ? value
    : minimum;
}

function seats(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return Array.from(
    new Set(
      value
        .slice(0, MAX_PLAYERS)
        .filter(
          (seat): seat is number =>
            typeof seat === "number" &&
            Number.isInteger(seat) &&
            seat >= 0 &&
            seat < MAX_PLAYERS,
        ),
    ),
  );
}

function players(value: unknown): Player[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<number>();
  const result: Player[] = [];
  for (const raw of value.slice(0, MAX_PLAYERS)) {
    if (!raw || typeof raw !== "object") continue;
    const seat = Reflect.get(raw, "seat");
    if (
      typeof seat !== "number" ||
      !Number.isInteger(seat) ||
      seat < 0 ||
      seat >= MAX_PLAYERS ||
      seen.has(seat)
    ) {
      continue;
    }
    const rawName = Reflect.get(raw, "name");
    result.push({
      seat,
      name:
        typeof rawName === "string" && rawName.trim()
          ? rawName.trim().slice(0, 64)
          : `Agent ${seat}`,
    });
    seen.add(seat);
  }
  return result.sort((left, right) => left.seat - right.seat);
}

function missions(value: unknown): Mission[] {
  if (!Array.isArray(value)) return [];
  const result: Mission[] = [];
  for (const raw of value.slice(0, MAX_MISSIONS)) {
    if (!raw || typeof raw !== "object") continue;
    const outcome = Reflect.get(raw, "outcome");
    if (
      outcome !== "repaired" &&
      outcome !== "sabotaged" &&
      outcome !== "sabotaged_by_deadlock"
    ) {
      continue;
    }
    result.push({
      round: integer(Reflect.get(raw, "round"), 1, MAX_MISSIONS),
      outcome,
      team: seats(Reflect.get(raw, "team")),
      sabotages: integer(Reflect.get(raw, "sabotages"), 0, MAX_PLAYERS),
    });
  }
  return result;
}

function roleMap(value: unknown, terminal: boolean): Map<number, Role> {
  const result = new Map<number, Role>();
  if (!terminal || !Array.isArray(value)) return result;
  for (const raw of value.slice(0, MAX_PLAYERS)) {
    if (!raw || typeof raw !== "object") continue;
    const seat = Reflect.get(raw, "seat");
    const role = Reflect.get(raw, "role");
    if (
      typeof seat === "number" &&
      Number.isInteger(seat) &&
      seat >= 0 &&
      seat < MAX_PLAYERS &&
      (role === "maintainer" || role === "corrupted")
    ) {
      result.set(seat, role);
    }
  }
  return result;
}

function score(value: unknown, key: string): number {
  return value && typeof value === "object"
    ? integer(Reflect.get(value, key), 0, 3)
    : 0;
}

function phaseName(value: unknown, terminal: boolean): string {
  if (terminal) return "Final reveal";
  if (value === "vote") return "Trust vote";
  if (value === "mission") return "Secret repair";
  return "Team proposal";
}

function MissionMarker({ mission }: { mission?: Mission }) {
  const repaired = mission?.outcome === "repaired";
  const sabotaged = mission && !repaired;
  return (
    <div
      className={`flex h-11 w-11 items-center justify-center rounded-full border-2 font-mono text-sm font-black ${
        repaired
          ? "border-[#22ffd1] bg-[#22ffd1]/15 text-[#22ffd1]"
          : sabotaged
            ? "border-[#ff5470] bg-[#ff5470]/15 text-[#ff5470]"
            : "border-edge bg-[#0a0f18] text-muted"
      }`}
      title={
        mission
          ? `${mission.outcome.replaceAll("_", " ")} · ${mission.sabotages} sabotage actions`
          : "Pending mission"
      }
    >
      {repaired ? "✓" : sabotaged ? "✕" : "·"}
    </div>
  );
}

/** Public-safe social dashboard. Roles render only on an explicit terminal frame. */
export default function LastServerRenderer({
  render,
}: {
  render: LastServerRender;
}) {
  const terminal = render?.terminal === true;
  const roster = players(render?.players);
  const history = missions(render?.missions);
  const roles = roleMap(render?.roles, terminal);
  const selected = new Set(seats(render?.proposed_team));
  const coordinator = integer(render?.coordinator, 0, MAX_PLAYERS - 1);
  const turn = integer(render?.turn, 0, MAX_PLAYERS - 1);
  const round = integer(render?.round, 1, MAX_MISSIONS);
  const repairs = score(render?.scores, "repairs");
  const sabotages = score(render?.scores, "sabotages");
  const winner =
    terminal &&
    (render?.winner_faction === "maintainer" ||
      render?.winner_faction === "corrupted")
      ? render.winner_faction
      : null;
  const phase = phaseName(render?.phase, terminal);
  const label = terminal
    ? `Last Server final reveal${winner ? `, ${winner} faction wins` : ""}`
    : `Last Server round ${round}, ${phase.toLowerCase()}`;

  return (
    <section
      role="img"
      aria-label={label}
      className="relative overflow-hidden rounded-xl border border-edge bg-[#060911] p-4 shadow-[inset_0_0_70px_rgba(34,255,209,0.04)]"
    >
      <div className="pointer-events-none absolute inset-0 opacity-20 [background-image:linear-gradient(rgba(34,255,209,.08)_1px,transparent_1px),linear-gradient(90deg,rgba(34,255,209,.08)_1px,transparent_1px)] [background-size:24px_24px]" />

      <div className="relative flex flex-col gap-4">
        <header className="flex flex-wrap items-center gap-3">
          <div>
            <p className="mb-0 font-mono text-[10px] uppercase tracking-[0.3em] text-muted">
              Cluster LS-01 · Round {round}/{MAX_MISSIONS}
            </p>
            <h2 className="mb-0 text-xl font-black tracking-tight text-neon">
              LAST SERVER
            </h2>
          </div>
          <div className="ml-auto rounded-full border border-accent/40 bg-accent/10 px-3 py-1 font-mono text-xs uppercase tracking-wider text-accent">
            {phase}
          </div>
        </header>

        {terminal && winner && (
          <div
            className={`rounded-lg border px-4 py-3 text-center font-mono text-sm font-black uppercase tracking-[0.18em] ${
              winner === "maintainer"
                ? "border-[#22ffd1] bg-[#22ffd1]/10 text-[#22ffd1]"
                : "border-[#ff5470] bg-[#ff5470]/10 text-[#ff5470]"
            }`}
          >
            {winner} faction wins
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-[#22ffd1]/30 bg-[#081616] p-3">
            <div className="flex items-center justify-between text-xs uppercase tracking-wider text-[#22ffd1]">
              <span>Repairs</span>
              <strong>{repairs}/3</strong>
            </div>
            <div className="mt-2 flex gap-1">
              {Array.from({ length: 3 }, (_, index) => (
                <span
                  key={index}
                  className={`h-2 flex-1 rounded-full ${index < repairs ? "bg-[#22ffd1] shadow-[0_0_8px_#22ffd1]" : "bg-[#183532]"}`}
                />
              ))}
            </div>
          </div>
          <div className="rounded-lg border border-[#ff5470]/30 bg-[#180b12] p-3">
            <div className="flex items-center justify-between text-xs uppercase tracking-wider text-[#ff5470]">
              <span>Sabotage</span>
              <strong>{sabotages}/3</strong>
            </div>
            <div className="mt-2 flex gap-1">
              {Array.from({ length: 3 }, (_, index) => (
                <span
                  key={index}
                  className={`h-2 flex-1 rounded-full ${index < sabotages ? "bg-[#ff5470] shadow-[0_0_8px_#ff5470]" : "bg-[#3a1823]"}`}
                />
              ))}
            </div>
          </div>
        </div>

        <div className="flex items-center justify-center gap-3 py-1">
          {Array.from({ length: MAX_MISSIONS }, (_, index) => (
            <MissionMarker key={index} mission={history[index]} />
          ))}
        </div>

        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
          {roster.map((player) => {
            const role = roles.get(player.seat);
            const isCoordinator = player.seat === coordinator && !terminal;
            const isTurn = player.seat === turn && !terminal;
            return (
              <article
                key={player.seat}
                className={`relative min-w-0 rounded-lg border p-3 ${
                  role === "corrupted"
                    ? "border-[#ff5470]/60 bg-[#ff5470]/10"
                    : role === "maintainer"
                      ? "border-[#22ffd1]/50 bg-[#22ffd1]/8"
                      : selected.has(player.seat)
                        ? "border-accent bg-accent/10"
                        : "border-edge bg-[#0a0f18]"
                } ${isTurn ? "ring-1 ring-neon" : ""}`}
              >
                <div className="flex items-center gap-2">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-current font-mono text-xs text-muted">
                    {player.seat}
                  </span>
                  <span
                    className="truncate text-sm font-semibold"
                    title={player.name}
                  >
                    {player.name}
                  </span>
                </div>
                <div className="mt-2 flex min-h-5 flex-wrap gap-1">
                  {isCoordinator && <span className="badge">Coordinator</span>}
                  {selected.has(player.seat) && !terminal && (
                    <span className="badge running">Selected</span>
                  )}
                  {role && (
                    <span
                      className={`text-[10px] font-black uppercase tracking-wider ${
                        role === "corrupted"
                          ? "text-[#ff5470]"
                          : "text-[#22ffd1]"
                      }`}
                    >
                      {role}
                    </span>
                  )}
                </div>
              </article>
            );
          })}
        </div>

        {!terminal && (
          <footer className="rounded-lg border border-edge bg-black/25 px-3 py-2 font-mono text-xs text-muted">
            {render?.phase === "vote"
              ? `${integer(render?.votes_submitted, 0, MAX_PLAYERS)}/${roster.length || 6} encrypted votes received`
              : render?.phase === "mission"
                ? `${integer(render?.mission_actions_submitted, 0, MAX_PLAYERS)}/${selected.size} private mission actions received`
                : `Coordinator ${coordinator} must nominate ${integer(render?.team_size, 1, MAX_PLAYERS)} agents`}
            {integer(render?.rejected_proposals, 0, 3) > 0 && (
              <span className="ml-2 text-[#ffb454]">
                · {integer(render?.rejected_proposals, 0, 3)}/3 proposals
                rejected
              </span>
            )}
          </footer>
        )}
      </div>
    </section>
  );
}
