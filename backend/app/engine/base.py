"""Shared game-engine interface and deterministic clock support.

Every game subclasses :class:`BaseGame`. The MatchManager drives all engines
through this one interface, so engines are pure (no Redis, no ORM, no I/O) and
fully deterministic given `(config, seed, seats)`.

Contract (shared, implement in every engine):
  mode                    class attr, "realtime" | "turnbased"
  REVEAL_SEED_DURING_PLAY class attr, false when a seed determines live secrets
  CONFIG_DEFAULTS         class attr, merged under Match.config
  __init__(config, seed, seats)
  reset()                 reinitialize to the start position
  get_render_data()       minimal data the web UI needs to draw
  observe(perspective=None) -> dict   state, scores, actions, and clock data

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
simulation choices.
"""

from __future__ import annotations

import random
import time
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel


class IllegalMove(ValueError):
    """Raised by turn-based apply_action for an illegal or out-of-turn move."""

    def __init__(self, code: str = "invalid_move", message: str = "Illegal move") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class BaseGame(ABC):
    mode: str = "realtime"
    name: str = "base"
    REVEAL_SEED_DURING_PLAY: bool = True
    CONFIG_DEFAULTS: dict[str, Any] = {}
    CONFIG_MODEL: type[BaseModel] | None = None

    @classmethod
    def normalize_config(cls, config: dict | None) -> dict[str, Any]:
        """Validate and materialize defaults for a trusted engine config."""
        raw_config = {**cls.CONFIG_DEFAULTS, **(config or {})}
        if cls.CONFIG_MODEL is None:
            return raw_config
        validated = cls.CONFIG_MODEL.model_validate(raw_config)
        return validated.model_dump(mode="python")

    def __init__(self, config: dict, seed: int, seats: list[dict]) -> None:
        self.config = self.normalize_config(config)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= 2**63 - 1:
            raise ValueError("seed must be an integer between 0 and 2^63 - 1")
        if self.CONFIG_MODEL is not None:
            expected_players = self.config.get("players_required", self.config.get("max_players"))
            if expected_players is not None and len(seats) != expected_players:
                raise ValueError(f"expected {expected_players} seats, received {len(seats)}")
            if [player.get("seat") for player in seats] != list(range(len(seats))):
                raise ValueError("seats must be ordered and numbered from zero")
        self.seed = seed
        self.seats: list[dict] = seats  # ordered [{"agent_id","seat","side","name"}]
        # Deterministic simulation, not a security primitive.
        self.rng: random.Random = random.Random(self.seed)  # noqa: S311
        self.move_count: int = 0
        self._terminal: bool = False
        self._winner: list[int] | None = None
        self.reset()
        self._initialize_clock()

    @abstractmethod
    def reset(self) -> None: ...

    @abstractmethod
    def get_render_data(self) -> dict: ...

    def get_legal_actions(self, seat: int) -> list[Any]:
        """Optional — strongly recommended (spec 4.4)."""
        return []

    def legal_actions_exhaustive(self, seat: int) -> bool:
        """Whether ``get_legal_actions`` enumerates every valid action.

        Engines with a combinatorial setup action may return a bounded schema
        descriptor instead. The engine must then validate that action
        transactionally in ``apply_action``. Normal play should remain
        exhaustive so the host can reject invalid actions before buffering.
        """
        return True

    def validate_action(self, action: Any, seat: int) -> None:
        """Validate a non-exhaustively advertised action without mutation.

        Most engines are guarded by exact membership in ``legal_actions`` and
        need no additional work. Engines returning a schema descriptor must
        override this hook so the API can reject malformed actions before they
        enter the asynchronous turn buffer.
        """
        return None

    def observe(self, perspective: int | None = None) -> dict:
        """Return the game-specific observation block (state, scores, summary,
        legal_actions, last_move, time). ``perspective`` is a participant seat
        for games with private state; ``None`` must always be spectator-safe."""
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

    # turn-based clock support (manager calls these) -------------------------
    def _clock_config(self) -> dict[str, Any]:
        return self.config.get("time_control") or {}

    def _clock_enabled(self) -> bool:
        return bool(self._clock_config().get("enabled"))

    def _initialize_clock(self) -> None:
        """Start a Fischer clock with only the side to move running."""
        tc = self._clock_config()
        base_ms = int(tc.get("base_sec", 60)) * 1000
        self._clock_remaining_ms = {seat: base_ms for seat in range(len(self.seats))}
        self._active_clock_seat: int | None = None
        self._clock_started_at: float | None = None
        if self._clock_enabled() and self.mode == "turnbased" and not self.is_terminal():
            self._active_clock_seat = self.current_seat()
            self._clock_started_at = time.monotonic()

    def _remaining_at(self, seat: int, now: float) -> int:
        remaining = self._clock_remaining_ms.get(seat, 0)
        if seat == self._active_clock_seat and self._clock_started_at is not None:
            remaining -= int((now - self._clock_started_at) * 1000)
        return max(0, remaining)

    def _freeze_clock(self, now: float | None = None) -> None:
        if not self._clock_enabled() or self._active_clock_seat is None:
            return
        stopped_at = time.monotonic() if now is None else now
        seat = self._active_clock_seat
        self._clock_remaining_ms[seat] = self._remaining_at(seat, stopped_at)
        self._active_clock_seat = None
        self._clock_started_at = None

    def _note_move(self, seat: int) -> None:
        """Commit elapsed time, add increment, and start the opponent's clock."""
        self.move_count += 1
        if not self._clock_enabled():
            return
        now = time.monotonic()
        if seat != self._active_clock_seat:
            raise RuntimeError(
                f"seat {seat} moved while seat {self._active_clock_seat} clock was active"
            )
        self._clock_remaining_ms[seat] = self._remaining_at(seat, now)
        increment_ms = int(self._clock_config().get("increment_sec", 0)) * 1000
        self._clock_remaining_ms[seat] += increment_ms
        self._active_clock_seat = self.current_seat()
        self._clock_started_at = now

    def _set_result(self, winner: list[int] | None) -> None:
        """Mark the game terminal. winner=None => draw / no winner."""
        self._freeze_clock()
        self._terminal = True
        self._winner = winner

    def clock_ms(self, seat: int) -> int | None:
        """Remaining ms for `seat`, or None when time control is disabled."""
        if not self._clock_enabled():
            return None
        if seat not in self._clock_remaining_ms:
            raise ValueError(f"unknown seat {seat}")
        return self._remaining_at(seat, time.monotonic())

    def clock_state(self) -> dict[str, Any] | None:
        """Serializable clock state keyed by stable agent id (or seat fallback)."""
        if not self._clock_enabled():
            return None
        now = time.monotonic()
        remaining: dict[str, int] = {}
        for seat, player in enumerate(self.seats):
            key = str(player.get("agent_id", seat))
            remaining[key] = self._remaining_at(seat, now)
        tc = self._clock_config()
        return {
            "remaining_ms": remaining,
            "increment_ms": int(tc.get("increment_sec", 0)) * 1000,
            "active_seat": self._active_clock_seat,
        }

    def timeout_loss(self, seat: int) -> None:
        """Declare the other player(s) the winners on clock timeout at `seat`."""
        remaining = self.clock_ms(seat)
        if remaining is None:
            raise RuntimeError("cannot declare a clock timeout without time control")
        if remaining > 0:
            raise RuntimeError(f"seat {seat} still has {remaining} ms remaining")
        self._clock_remaining_ms[seat] = 0
        self._set_result([s for s in range(len(self.seats)) if s != seat] or None)

    # shared terminal -------------------------------------------------------
    def is_terminal(self) -> bool:
        return bool(self._terminal)

    def get_winner(self) -> list[int] | None:
        return self._winner

    def get_scores(self) -> dict:
        return {}

    def summary(self) -> str:
        return f"{self.name} in progress"
