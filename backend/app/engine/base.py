"""Game engine plugin interface (spec §8, §9, §14).

Every game subclasses :class:`BaseGame`. The MatchManager drives all engines
through this one interface, so engines are pure (no Redis, no ORM, no I/O) and
fully deterministic given `(config, seed, seats)`.

Contract (shared, implement in every engine):
  mode                    class attr, "realtime" | "turnbased"
  CONFIG_DEFAULTS         class attr, merged under Match.config
  __init__(config, seed, seats)
  reset()                 reinitialize to the start position
  get_render_data()       minimal data the web UI needs to draw
  observe(perspective=None) -> dict   full §4.4 `state`-level block

Realtime engines additionally implement:
  step(moves)             advance one tick, where moves = {seat: action|None}
                          (missing action -> documented noop/last-allowed)

Turn-based engines additionally implement:
  current_seat()          seat index that must move
  apply_action(action)    advance on a legal move; raises IllegalMove on invalid
  get_legal_actions(seat) list of legal actions for `seat`
  clock_ms(seat)/timeout_loss(seat)  provided by BaseGame from time_control config;
                          no per-engine work needed for clocks

Terminal handling (shared):
  To support clock timeouts, do NOT override is_terminal()/get_winner(); instead
  call self._set_result(winner_seats) (or raise a draw via _set_result(None)) when
  the game ends naturally. BaseGame.is_terminal()/get_winner() then reflect both
  natural endings and timeouts. (A game without time control may still override
  these if it prefers—the manager only calls the public methods.)

All engines get a seeded `self.rng = random.Random(seed)` for deterministic
food/piece/deal spawning.
"""
from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import Any


class IllegalMove(ValueError):
    """Raised by turn-based apply_action for an illegal or out-of-turn move."""

    def __init__(self, code: str = "invalid_move", message: str = "Illegal move") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BaseGame(ABC):
    mode: str = "realtime"
    name: str = "base"
    CONFIG_DEFAULTS: dict[str, Any] = {}

    def __init__(self, config: dict, seed: int, seats: list[dict]) -> None:
        self.config: dict = {**self.CONFIG_DEFAULTS, **(config or {})}
        self.seed: int = int(seed)
        self.seats: list[dict] = seats  # ordered [{"agent_id","seat","side","name"}]
        self.rng: random.Random = random.Random(self.seed)
        self.move_count: int = 0
        self._seat_clock: dict[int, float] = {
            s: time.monotonic() for s in range(len(seats))
        }
        self._terminal: bool = False
        self._winner: list[int] | None = None
        self.reset()

    @abstractmethod
    def reset(self) -> None:
        ...

    @abstractmethod
    def get_render_data(self) -> dict:
        ...

    def get_legal_actions(self, seat: int) -> list[Any]:
        """Optional — strongly recommended (spec 4.4)."""
        return []

    def observe(self, perspective: int | None = None) -> dict:
        """Return the game-specific observation block (state, scores, summary,
        legal_actions, last_move, time). perspective is a seat index for
        symmetric-hidden-info games (chess/mancala), else ignored."""
        raise NotImplementedError

    # realtime path ---------------------------------------------------------
    def step(self, moves: dict[int, Any]) -> None:
        """Advance one tick. `moves` maps seat index -> submitted action.
        Called by the manager each tick for mode=realtime engines."""
        raise NotImplementedError(f"{self.__class__.__name__} is not a realtime engine")

    # turn-based path -------------------------------------------------------
    def current_seat(self) -> int:
        raise NotImplementedError(f"{self.__class__.__name__} is not a turn-based engine")

    def apply_action(self, action: Any) -> None:
        """Advance on a legal move; raise IllegalMove otherwise."""
        raise NotImplementedError(f"{self.__class__.__name__} is not a turn-based engine")

    # turn-based clock support (manager calls these) --------------------------
    def _note_move(self, seat: int) -> None:
        """Turn-based engines call after a successful apply_action."""
        self.move_count += 1
        self._seat_clock[seat] = time.monotonic()

    def _set_result(self, winner: list[int] | None) -> None:
        """Mark the game terminal. winner=None => draw / no winner."""
        self._terminal = True
        self._winner = winner

    def clock_ms(self, seat: int) -> int | None:
        """Remaining ms for `seat`, or None when time control is disabled."""
        tc = self.config.get("time_control") or {}
        if not tc.get("enabled"):
            return None
        base = int(tc.get("base_sec", 60)) * 1000
        inc = int(tc.get("increment_sec", 0)) * 1000
        last = self._seat_clock.get(seat, time.monotonic())
        return max(0, base + inc - int((time.monotonic() - last) * 1000))

    def timeout_loss(self, seat: int) -> None:
        """Declare the other player(s) the winners on clock timeout at `seat`."""
        self._set_result([s for s in range(len(self.seats)) if s != seat] or None)
        self._note_move(seat)

    # shared terminal -------------------------------------------------------
    def is_terminal(self) -> bool:
        return bool(self._terminal)

    def get_winner(self) -> list[int] | None:
        return self._winner

    def get_scores(self) -> dict:
        return {}

    def summary(self) -> str:
        return f"{self.name} in progress"
