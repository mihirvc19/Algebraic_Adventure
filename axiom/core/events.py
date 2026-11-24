"""Typed, immutable events emitted by the core for a presentation layer.

The core never calls into a UI. It returns lists of these events, in order,
and a future Pygame/Raylib front end can map each one to an animation or
sound. Every event is a frozen dataclass, so it maps onto a C++
``std::variant`` of plain structs.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from .equation import Equation, Side


@dataclass(frozen=True, slots=True)
class CombatEvent:
    """Marker base class for every event."""


@dataclass(frozen=True, slots=True)
class TurnStartedEvent(CombatEvent):
    turn: int
    ap: int
    hand: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EnemyIntentTelegraphedEvent(CombatEvent):
    enemy_name: str
    intent: str


@dataclass(frozen=True, slots=True)
class CardPlayedEvent(CombatEvent):
    card_name: str
    ap_spent: int
    ap_remaining: int


@dataclass(frozen=True, slots=True)
class TermCancelledEvent(CombatEvent):
    side: Side
    term: str


@dataclass(frozen=True, slots=True)
class EquationMutatedEvent(CombatEvent):
    source: str
    before: Equation
    after: Equation


@dataclass(frozen=True, slots=True)
class MessyFractionWarningEvent(CombatEvent):
    divisor: Fraction
    equation: Equation


@dataclass(frozen=True, slots=True)
class SolutionStrikeEvent(CombatEvent):
    """The player executed a solved equation; this hit is fatal to the enemy."""

    solution: Fraction


@dataclass(frozen=True, slots=True)
class ActionUndoneEvent(CombatEvent):
    card_name: str
    restored: Equation


@dataclass(frozen=True, slots=True)
class EnemyIntentTriggeredEvent(CombatEvent):
    enemy_name: str
    intent: str
    kind: str
    magnitude: int


@dataclass(frozen=True, slots=True)
class PlayerDamagedEvent(CombatEvent):
    amount: int
    hp_remaining: int


@dataclass(frozen=True, slots=True)
class CombatEndedEvent(CombatEvent):
    victory: bool
    turns: int
