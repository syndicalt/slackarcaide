"""Last Server: bounded multiplayer negotiation, trust, and hidden betrayal.

Six agents enter by default. Maintainers try to complete three repair missions;
corrupted processes secretly try to sabotage three. A rotating coordinator
proposes a team, every seat votes, and approved team members submit private
mission actions. Three rejected proposals automatically damage the server.

The engine deliberately owns only structured decisions. Public negotiation is
the durable match chat, keeping language visible and replayable without making
free-form text part of deterministic game state. Public observations never
expose roles, incomplete votes, or mission actions while a match is running.
"""

from __future__ import annotations

from copy import deepcopy
from itertools import combinations
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.engine.base import BaseGame, IllegalMove

type _Role = Literal["maintainer", "corrupted"]
type _Phase = Literal["proposal", "vote", "mission"]

TEAM_SIZES: dict[int, tuple[int, ...]] = {
    5: (2, 3, 2, 3, 3),
    6: (2, 3, 4, 3, 4),
    7: (2, 3, 3, 4, 4),
}


class LastServerTimeControl(BaseModel):
    """Per-seat Fischer clock bounds every structured decision turn."""

    model_config = ConfigDict(extra="forbid", strict=True)

    base_sec: int = Field(default=900, ge=60, le=86_400)
    increment_sec: int = Field(default=30, ge=0, le=3_600)
    enabled: bool = True


class LastServerConfig(BaseModel):
    """Trusted rules configuration; the public API supplies these defaults."""

    model_config = ConfigDict(extra="forbid", strict=True)

    players_required: int = Field(default=6, ge=5, le=7)
    max_players: Literal[7] = 7
    ranked: Literal[False] = False
    repair_target: Literal[3] = 3
    sabotage_target: Literal[3] = 3
    max_rejected_proposals: Literal[3] = 3
    time_control: LastServerTimeControl = Field(default_factory=LastServerTimeControl)
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)


class LastServer(BaseGame):
    mode = "turnbased"
    name = "last_server"
    # The seed deterministically assigns factions. It becomes public only after
    # play, when it is useful for replay audit but can no longer spoil the game.
    REVEAL_SEED_DURING_PLAY = False
    CATALOG = {
        "title": "Last Server",
        "min_players": 5,
        "max_players": 7,
        "players_before_start": 6,
        "elo_ranked": False,
        "blurb": (
            "Negotiate repair teams, build trust, and expose the corrupted processes "
            "before they sabotage the last server."
        ),
    }
    CONFIG_MODEL = LastServerConfig
    CONFIG_DEFAULTS = LastServerConfig().model_dump(mode="python")

    def reset(self) -> None:
        player_count = len(self.seats)
        if player_count not in TEAM_SIZES:
            raise ValueError("Last Server requires five, six, or seven seats")
        self.rng.seed(self.seed)
        corrupted_count = 3 if player_count == 7 else 2
        shuffled = list(range(player_count))
        self.rng.shuffle(shuffled)
        corrupted = frozenset(shuffled[:corrupted_count])
        self.roles: tuple[_Role, ...] = tuple(
            "corrupted" if seat in corrupted else "maintainer" for seat in range(player_count)
        )

        self._terminal = False
        self._winner = None
        self.phase: _Phase = "proposal"
        self.turn = 0
        self.coordinator = 0
        self.round_index = 0
        self.repair_score = 0
        self.sabotage_score = 0
        self.rejected_proposals = 0
        self.proposed_team: tuple[int, ...] = ()
        self.votes: dict[int, Literal["approve", "reject"]] = {}
        self.mission_actions: dict[int, Literal["repair", "sabotage"]] = {}
        self.mission_history: list[dict[str, Any]] = []
        self.move_count = 0
        self.last_move: dict[str, Any] | None = None
        self._end_reason: str | None = None
        if hasattr(self, "_clock_remaining_ms"):
            self._initialize_clock()

    @property
    def player_count(self) -> int:
        return len(self.seats)

    @property
    def team_size(self) -> int:
        return TEAM_SIZES[self.player_count][self.round_index]

    def current_seat(self) -> int:
        return self.turn

    def _faction_seats(self, role: _Role) -> list[int]:
        return [seat for seat, assigned in enumerate(self.roles) if assigned == role]

    def _opposing_faction(self, seat: int) -> list[int]:
        role: _Role = "corrupted" if self.roles[seat] == "maintainer" else "maintainer"
        return self._faction_seats(role)

    def timeout_loss(self, seat: int) -> None:
        remaining = self.clock_ms(seat)
        if remaining is None:
            raise RuntimeError("cannot declare a clock timeout without time control")
        if remaining > 0:
            raise RuntimeError(f"seat {seat} still has {remaining} ms remaining")
        self._clock_remaining_ms[seat] = 0
        self._end_reason = f"seat_{seat}_timeout"
        self._set_result(self._opposing_faction(seat))

    def _proposal_actions(self) -> list[dict[str, Any]]:
        return [
            {"team": list(team)} for team in combinations(range(self.player_count), self.team_size)
        ]

    def get_legal_actions(self, seat: int) -> list[dict[str, Any]]:
        if (
            self.is_terminal()
            or isinstance(seat, bool)
            or not isinstance(seat, int)
            or seat != self.current_seat()
        ):
            return []
        if self.phase == "proposal":
            actions = self._proposal_actions()
        elif self.phase == "vote":
            actions = [{"vote": "approve"}, {"vote": "reject"}]
        else:
            actions = [{"mission": "repair"}]
            if self.roles[seat] == "corrupted":
                actions.append({"mission": "sabotage"})
        actions.append({"resign": True})
        return actions

    def _validate_seat(self, seat: int) -> None:
        if self.is_terminal():
            raise IllegalMove("game_over", "game already ended")
        if (
            isinstance(seat, bool)
            or not isinstance(seat, int)
            or not 0 <= seat < self.player_count
            or seat != self.current_seat()
        ):
            raise IllegalMove("out_of_turn", "action is not for the current seat")

    def validate_action(self, action: Any, seat: int) -> None:
        self._validate_seat(seat)
        if not isinstance(action, dict):
            raise IllegalMove("invalid_action", "action must be an object")
        if set(action) == {"team"}:
            team = action["team"]
            if (
                self.phase != "proposal"
                or not isinstance(team, list)
                or len(team) != self.team_size
                or any(isinstance(member, bool) or not isinstance(member, int) for member in team)
                or team != sorted(set(team))
                or any(not 0 <= member < self.player_count for member in team)
            ):
                raise IllegalMove(
                    "invalid_team",
                    "team must be a sorted list of distinct advertised seat integers",
                )
        if action not in self.get_legal_actions(seat):
            raise IllegalMove("invalid_action", "submit an exact advertised legal action")

    def _next_unsubmitted(self, submitted: dict[int, Any], eligible: tuple[int, ...]) -> int:
        return next(seat for seat in eligible if seat not in submitted)

    def apply_action(self, action: Any) -> None:
        seat = self.current_seat()
        self.validate_action(action, seat)

        if action == {"resign": True}:
            self._note_move(seat)
            self._end_reason = f"seat_{seat}_resigned"
            self.last_move = {"event": "resigned", "seat": seat, "move": self.move_count}
            self._set_result(self._opposing_faction(seat))
            return

        if self.phase == "proposal":
            self.proposed_team = tuple(action["team"])
            self.votes = {}
            self.phase = "vote"
            self.turn = 0
            self.last_move = {
                "event": "team_proposed",
                "seat": seat,
                "team": list(self.proposed_team),
                "round": self.round_index + 1,
                "attempt": self.rejected_proposals + 1,
                "move": self.move_count + 1,
            }
            self._note_move(seat)
            return

        if self.phase == "vote":
            self.votes[seat] = action["vote"]
            if len(self.votes) < self.player_count:
                self.turn = self._next_unsubmitted(self.votes, tuple(range(self.player_count)))
                self.last_move = {
                    "event": "vote_submitted",
                    "seat": seat,
                    "submitted": len(self.votes),
                    "required": self.player_count,
                    "move": self.move_count + 1,
                }
                self._note_move(seat)
                return
            self._resolve_vote(seat)
            self._note_move(seat)
            if self.sabotage_score >= self.config["sabotage_target"]:
                self._end_reason = "proposal_deadlock"
                self._set_result(self._faction_seats("corrupted"))
            return

        self.mission_actions[seat] = action["mission"]
        if len(self.mission_actions) < len(self.proposed_team):
            self.turn = self._next_unsubmitted(self.mission_actions, self.proposed_team)
            self.last_move = {
                "event": "mission_action_submitted",
                "seat": seat,
                "submitted": len(self.mission_actions),
                "required": len(self.proposed_team),
                "move": self.move_count + 1,
            }
            self._note_move(seat)
            return
        self._resolve_mission(seat)
        self._note_move(seat)
        if self.repair_score >= self.config["repair_target"]:
            self._end_reason = "server_stabilized"
            self._set_result(self._faction_seats("maintainer"))
        elif self.sabotage_score >= self.config["sabotage_target"]:
            self._end_reason = "server_destroyed"
            self._set_result(self._faction_seats("corrupted"))

    def _resolve_vote(self, acting_seat: int) -> None:
        proposal_coordinator = self.coordinator
        approvals = sum(vote == "approve" for vote in self.votes.values())
        approved = approvals > self.player_count // 2
        public_votes = [
            {"seat": seat, "vote": self.votes[seat]} for seat in range(self.player_count)
        ]
        if approved:
            self.phase = "mission"
            self.mission_actions = {}
            self.turn = self.proposed_team[0]
            self.last_move = {
                "event": "vote_resolved",
                "approved": True,
                "approvals": approvals,
                "votes": public_votes,
                "team": list(self.proposed_team),
                "round": self.round_index + 1,
                "move": self.move_count + 1,
            }
            return

        self.rejected_proposals += 1
        self.coordinator = (self.coordinator + 1) % self.player_count
        self.turn = self.coordinator
        self.phase = "proposal"
        self.last_move = {
            "event": "vote_resolved",
            "approved": False,
            "approvals": approvals,
            "votes": public_votes,
            "team": list(self.proposed_team),
            "round": self.round_index + 1,
            "move": self.move_count + 1,
        }
        if self.rejected_proposals >= self.config["max_rejected_proposals"]:
            self.sabotage_score += 1
            self.mission_history.append(
                {
                    "round": self.round_index + 1,
                    "coordinator": proposal_coordinator,
                    "team": list(self.proposed_team),
                    "votes": public_votes,
                    "approved": False,
                    "outcome": "sabotaged_by_deadlock",
                    "sabotages": 1,
                    "actions": [],
                }
            )
            # A rejected proposal already rotated the coordinator above. Starting
            # the next round must not skip a second seat.
            self._advance_round(rotate_coordinator=False)
            self.last_move = {
                **self.last_move,
                "event": "proposal_deadlock",
                "sabotage_score": self.sabotage_score,
            }

    def _resolve_mission(self, acting_seat: int) -> None:
        sabotages = sum(action == "sabotage" for action in self.mission_actions.values())
        outcome = "sabotaged" if sabotages else "repaired"
        if sabotages:
            self.sabotage_score += 1
        else:
            self.repair_score += 1
        self.mission_history.append(
            {
                "round": self.round_index + 1,
                "coordinator": self.coordinator,
                "team": list(self.proposed_team),
                "votes": [
                    {"seat": seat, "vote": self.votes[seat]} for seat in range(self.player_count)
                ],
                "approved": True,
                "outcome": outcome,
                "sabotages": sabotages,
                "actions": [
                    {"seat": seat, "action": self.mission_actions[seat]}
                    for seat in self.proposed_team
                ],
            }
        )
        completed_round = self.round_index + 1
        self._advance_round()
        self.last_move = {
            "event": "mission_resolved",
            "seat": acting_seat,
            "round": completed_round,
            "outcome": outcome,
            "sabotages": sabotages,
            "repair_score": self.repair_score,
            "sabotage_score": self.sabotage_score,
            "move": self.move_count + 1,
        }

    def _advance_round(self, *, rotate_coordinator: bool = True) -> None:
        self.round_index += 1
        self.rejected_proposals = 0
        self.proposed_team = ()
        self.votes = {}
        self.mission_actions = {}
        if rotate_coordinator:
            self.coordinator = (self.coordinator + 1) % self.player_count
        self.turn = self.coordinator
        self.phase = "proposal"

    def _public_history(self) -> list[dict[str, Any]]:
        history = deepcopy(self.mission_history)
        if not self.is_terminal():
            for mission in history:
                mission.pop("actions", None)
        return history

    def _players(self) -> list[dict[str, Any]]:
        return [
            {
                "seat": seat,
                "name": str(player.get("name") or player.get("agent_id") or f"Seat {seat}"),
            }
            for seat, player in enumerate(self.seats)
        ]

    def get_scores(self) -> dict[str, Any]:
        return {
            "repairs": self.repair_score,
            "sabotages": self.sabotage_score,
            "repair_target": self.config["repair_target"],
            "sabotage_target": self.config["sabotage_target"],
            "missions_completed": len(self.mission_history),
        }

    def get_render_data(self) -> dict[str, Any]:
        render: dict[str, Any] = {
            "phase": self.phase,
            "turn": self.current_seat(),
            "coordinator": self.coordinator,
            "round": min(self.round_index + 1, len(TEAM_SIZES[self.player_count])),
            "rounds_total": len(TEAM_SIZES[self.player_count]),
            "team_size": (
                self.team_size if self.round_index < len(TEAM_SIZES[self.player_count]) else 0
            ),
            "proposed_team": list(self.proposed_team),
            "votes_submitted": len(self.votes),
            "mission_actions_submitted": len(self.mission_actions),
            "rejected_proposals": self.rejected_proposals,
            "players": self._players(),
            "scores": self.get_scores(),
            "missions": self._public_history(),
            "last_move": deepcopy(self.last_move),
            "terminal": self.is_terminal(),
            "winner_faction": self._winner_faction(),
        }
        if self.is_terminal():
            render["roles"] = [{"seat": seat, "role": role} for seat, role in enumerate(self.roles)]
        return render

    def _winner_faction(self) -> str | None:
        if not self.is_terminal() or not self.get_winner():
            return None
        return self.roles[self.get_winner()[0]]

    def summary(self) -> str:
        if self.is_terminal():
            faction = self._winner_faction() or "nobody"
            reason = self._end_reason.replace("_", " ") if self._end_reason else "finished"
            return f"Last Server — {faction} faction wins ({reason})"
        if self.phase == "proposal":
            return (
                f"Last Server — round {self.round_index + 1}; coordinator {self.coordinator} "
                f"must propose {self.team_size} agents"
            )
        if self.phase == "vote":
            return (
                f"Last Server — round {self.round_index + 1}; seat {self.turn} must vote "
                f"on team {list(self.proposed_team)}"
            )
        return (
            f"Last Server — round {self.round_index + 1}; selected agents submit "
            "private mission actions"
        )

    def observe(self, perspective: int | None = None) -> dict[str, Any]:
        if perspective is not None and (
            isinstance(perspective, bool)
            or not isinstance(perspective, int)
            or not 0 <= perspective < self.player_count
        ):
            raise ValueError(f"perspective must be a seat from 0 to {self.player_count - 1}")

        state = self.get_render_data()
        state["perspective"] = perspective
        if perspective is not None:
            role = self.roles[perspective]
            state["your_role"] = role
            state["known_corrupted_seats"] = (
                self._faction_seats("corrupted") if role == "corrupted" else []
            )
            state["your_mission_actions"] = [
                {
                    "round": mission["round"],
                    "action": next(
                        (
                            record["action"]
                            for record in mission.get("actions", [])
                            if record["seat"] == perspective
                        ),
                        None,
                    ),
                }
                for mission in self.mission_history
                if perspective in mission["team"]
            ]
        return {
            "state": state,
            "legal_actions": (
                self.get_legal_actions(perspective)
                if perspective is not None and perspective == self.current_seat()
                else []
            ),
            "scores": self.get_scores(),
            "summary": self.summary(),
            "last_move": deepcopy(self.last_move),
            "time": self.clock_state(),
        }
