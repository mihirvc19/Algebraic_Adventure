"""Turn-based combat finite state machine with a snapshot undo stack.

All combat data lives in immutable ``*State`` dataclasses. Every action
replaces ``CombatEngine.state`` with a new snapshot. Undo just restores an
earlier snapshot. Randomness comes from one seeded ``random.Random`` and is
only used at turn boundaries (dealing hands, picking enemy intents), so undo
within a turn never touches the RNG and replays stay deterministic.

Phase transitions::

    SETUP --start()--> PLAYER_TURN --end_turn()--> ENEMY_TURN --> PLAYER_TURN
                           |                           |
                           +--Execute Solve--> VICTORY +--HP <= 0--> DEFEAT
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from enum import Enum, auto
from typing import Callable, Literal, Sequence

from .ast_nodes import ConstantNode, to_fraction
from .cards import (
    AddConstantCard,
    CombineLikeTermsCard,
    DistributeCard,
    DivideCard,
    ExecuteSolveCard,
    MultiplyCard,
    OperationCard,
    SubtractConstantCard,
)
from .equation import Equation
from .events import (
    ActionUndoneEvent,
    CardPlayedEvent,
    CombatEndedEvent,
    CombatEvent,
    EnemyIntentTelegraphedEvent,
    EnemyIntentTriggeredEvent,
    EquationMutatedEvent,
    PlayerDamagedEvent,
    SolutionStrikeEvent,
    TurnStartedEvent,
)
from .generator import generate_equation
from .solver import plan_solution


class TurnPhase(Enum):
    SETUP = auto()
    PLAYER_TURN = auto()
    ENEMY_TURN = auto()
    VICTORY = auto()
    DEFEAT = auto()


class IllegalActionError(ValueError):
    """Raised when an action isn't allowed in the current state."""


IntentKind = Literal["ATTACK", "REINFORCE", "FORTIFY"]


@dataclass(frozen=True, slots=True)
class Intent:
    """What the enemy will do at the end of the player's turn (shown to the player in advance)."""

    kind: IntentKind
    magnitude: int

    @property
    def description(self) -> str:
        if self.kind == "ATTACK":
            return f"Attack {self.magnitude}"
        if self.kind == "REINFORCE":
            return f"Reinforce +{self.magnitude}"
        return f"Fortify x{self.magnitude}"


@dataclass(frozen=True, slots=True)
class CardInstance:
    """A card in a zone. ``uid`` is stable for UI tracking.

    Conjured cards are generated from context for one turn only. They are
    removed instead of discarded.
    """

    uid: int
    card: OperationCard
    conjured: bool = False


@dataclass(frozen=True, slots=True)
class PlayerState:
    hp: int
    max_hp: int
    ap: int
    max_ap: int
    deck: tuple[CardInstance, ...]
    hand: tuple[CardInstance, ...]
    discard: tuple[CardInstance, ...]


@dataclass(frozen=True, slots=True)
class EnemyState:
    name: str
    tier: int
    equation: Equation
    root: int
    intent: Intent | None = None


@dataclass(frozen=True, slots=True)
class CombatState:
    player: PlayerState
    enemy: EnemyState
    phase: TurnPhase
    turn: int
    next_uid: int


@dataclass(frozen=True, slots=True)
class CombatConfig:
    max_hp: int = 50
    max_ap: int = 3
    draw_count: int = 3
    complexity_cap: int = 14
    """Enemies stop adding terms once the equation has this many tokens."""


@dataclass(frozen=True, slots=True)
class _HistoryEntry:
    state_before: CombatState
    card_name: str


IntentPolicy = Callable[[EnemyState, random.Random, CombatConfig], Intent]


def default_intent_policy(enemy: EnemyState, rng: random.Random, config: CombatConfig) -> Intent:
    """Mostly attacks. Sometimes makes the equation harder instead."""
    roll = rng.random()
    simple_enough = len(enemy.equation.to_tokens()) < config.complexity_cap
    if simple_enough and enemy.tier >= 2 and roll < 0.15:
        return Intent("FORTIFY", 2)
    if simple_enough and roll < 0.40:
        return Intent("REINFORCE", rng.randint(1, 6))
    return Intent("ATTACK", rng.randint(1, 3) + 2 * enemy.tier)


def starter_deck() -> list[OperationCard]:
    return [
        CombineLikeTermsCard(),
        CombineLikeTermsCard(),
        DistributeCard(),
        ExecuteSolveCard(),
        ExecuteSolveCard(),
        AddConstantCard(1),
        SubtractConstantCard(1),
        MultiplyCard(2),
        DivideCard(2),
        DivideCard(3),
    ]


@dataclass
class CombatEngine:
    """Runs one encounter between the player and one equation-enemy."""

    enemy_name: str
    equation: Equation
    root: int
    tier: int = 1
    seed: int | None = None
    config: CombatConfig = field(default_factory=CombatConfig)
    player_hp: int | None = None
    deck: Sequence[OperationCard] | None = None
    intent_policy: IntentPolicy = default_intent_policy

    _rng: random.Random = field(init=False, repr=False)
    _state: CombatState = field(init=False, repr=False)
    _history: list[_HistoryEntry] = field(init=False, repr=False, default_factory=list)

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        cards = list(self.deck) if self.deck is not None else starter_deck()
        instances = tuple(CardInstance(uid, card) for uid, card in enumerate(cards))
        hp = self.config.max_hp if self.player_hp is None else self.player_hp
        if not 0 < hp <= self.config.max_hp:
            raise ValueError(f"player_hp must be in 1..{self.config.max_hp}")
        self._state = CombatState(
            player=PlayerState(
                hp=hp,
                max_hp=self.config.max_hp,
                ap=0,
                max_ap=self.config.max_ap,
                deck=instances,
                hand=(),
                discard=(),
            ),
            enemy=EnemyState(self.enemy_name, self.tier, self.equation, self.root),
            phase=TurnPhase.SETUP,
            turn=0,
            next_uid=len(instances),
        )

    @classmethod
    def from_generator(
        cls,
        enemy_name: str,
        tier: int,
        seed: int | None = None,
        *,
        config: CombatConfig | None = None,
        player_hp: int | None = None,
        deck: Sequence[OperationCard] | None = None,
        intent_policy: IntentPolicy = default_intent_policy,
    ) -> CombatEngine:
        """Build an encounter with a freshly generated equation for ``tier``."""
        equation, root = generate_equation(tier, seed)
        return cls(
            enemy_name,
            equation,
            root,
            tier,
            seed,
            config=config if config is not None else CombatConfig(),
            player_hp=player_hp,
            deck=deck,
            intent_policy=intent_policy,
        )

    # ---------------------------------------------------------------- queries

    @property
    def state(self) -> CombatState:
        return self._state

    @property
    def phase(self) -> TurnPhase:
        return self._state.phase

    @property
    def player(self) -> PlayerState:
        return self._state.player

    @property
    def enemy(self) -> EnemyState:
        return self._state.enemy

    @property
    def can_undo(self) -> bool:
        return self.phase is TurnPhase.PLAYER_TURN and bool(self._history)

    @property
    def is_over(self) -> bool:
        return self.phase in (TurnPhase.VICTORY, TurnPhase.DEFEAT)

    def unplayable_reason(self, hand_index: int) -> str | None:
        if self.phase is not TurnPhase.PLAYER_TURN:
            return f"cannot play cards during {self.phase.name}"
        hand = self.player.hand
        if not 0 <= hand_index < len(hand):
            return f"no card at hand position {hand_index}"
        card = hand[hand_index].card
        if card.cost > self.player.ap:
            return f"{card.name} costs {card.cost} AP but only {self.player.ap} AP remain"
        return card.unplayable_reason(self.enemy.equation)

    def can_play(self, hand_index: int) -> bool:
        return self.unplayable_reason(hand_index) is None

    def preview_card(self, hand_index: int) -> Equation:
        hand = self.player.hand
        if not 0 <= hand_index < len(hand):
            raise IllegalActionError(f"no card at hand position {hand_index}")
        return hand[hand_index].card.preview(self.enemy.equation)

    # ---------------------------------------------------------------- actions

    def start(self) -> list[CombatEvent]:
        self._require_phase(TurnPhase.SETUP)
        player = self._state.player
        deck = list(player.deck)
        self._rng.shuffle(deck)
        self._state = replace(self._state, player=replace(player, deck=tuple(deck)))
        return self._begin_player_turn()

    def play_card(self, hand_index: int) -> list[CombatEvent]:
        reason = self.unplayable_reason(hand_index)
        if reason is not None:
            raise IllegalActionError(reason)

        state = self._state
        player = state.player
        instance = player.hand[hand_index]
        card = instance.card
        new_equation, card_events = card.execute(state.enemy.equation)

        self._history.append(_HistoryEntry(state, card.name))
        hand = player.hand[:hand_index] + player.hand[hand_index + 1 :]
        discard = player.discard if instance.conjured else player.discard + (instance,)
        new_player = replace(player, ap=player.ap - card.cost, hand=hand, discard=discard)
        self._state = replace(
            state,
            player=new_player,
            enemy=replace(state.enemy, equation=new_equation),
        )

        events: list[CombatEvent] = [CardPlayedEvent(card.name, card.cost, new_player.ap)]
        events.extend(card_events)
        if any(isinstance(event, SolutionStrikeEvent) for event in card_events):
            self._state = replace(self._state, phase=TurnPhase.VICTORY)
            self._history.clear()
            events.append(CombatEndedEvent(victory=True, turns=self._state.turn))
        return events

    def undo_last_action(self) -> list[CombatEvent]:
        """Rewind the most recent card play of the current turn."""
        self._require_phase(TurnPhase.PLAYER_TURN)
        if not self._history:
            raise IllegalActionError("nothing to undo this turn")
        entry = self._history.pop()
        self._state = entry.state_before
        return [ActionUndoneEvent(entry.card_name, self._state.enemy.equation)]

    def end_turn(self) -> list[CombatEvent]:
        self._require_phase(TurnPhase.PLAYER_TURN)
        self._history.clear()
        state = self._state
        player = state.player
        kept = tuple(instance for instance in player.hand if not instance.conjured)
        self._state = replace(
            state,
            phase=TurnPhase.ENEMY_TURN,
            player=replace(player, hand=(), discard=player.discard + kept),
        )
        events = self._resolve_enemy_intent()
        if self.phase is TurnPhase.DEFEAT:
            return events
        events.extend(self._begin_player_turn())
        return events

    # -------------------------------------------------------------- internals

    def _require_phase(self, phase: TurnPhase) -> None:
        if self.phase is not phase:
            raise IllegalActionError(f"expected phase {phase.name}, currently {self.phase.name}")

    def _resolve_enemy_intent(self) -> list[CombatEvent]:
        state = self._state
        enemy = state.enemy
        intent = enemy.intent
        if intent is None:
            return []
        events: list[CombatEvent] = [
            EnemyIntentTriggeredEvent(enemy.name, intent.description, intent.kind, intent.magnitude)
        ]
        if intent.kind == "ATTACK":
            hp = max(0, state.player.hp - intent.magnitude)
            self._state = replace(state, player=replace(state.player, hp=hp))
            events.append(PlayerDamagedEvent(intent.magnitude, hp))
            if hp == 0:
                self._state = replace(self._state, phase=TurnPhase.DEFEAT)
                events.append(CombatEndedEvent(victory=False, turns=state.turn))
            return events

        op: Literal["+", "*"] = "+" if intent.kind == "REINFORCE" else "*"
        operand = ConstantNode(to_fraction(intent.magnitude))
        new_equation = enemy.equation.apply_binary_both_sides(op, operand)
        self._state = replace(state, enemy=replace(enemy, equation=new_equation))
        events.append(EquationMutatedEvent(enemy.name, enemy.equation, new_equation))
        return events

    def _begin_player_turn(self) -> list[CombatEvent]:
        state = self._state
        turn = state.turn + 1
        intent = self.intent_policy(state.enemy, self._rng, self.config)
        enemy = replace(state.enemy, intent=intent)
        self._state = replace(
            state,
            turn=turn,
            phase=TurnPhase.PLAYER_TURN,
            enemy=enemy,
            player=replace(state.player, ap=state.player.max_ap),
        )
        self._deal_hand()
        hand_names = tuple(instance.card.name for instance in self.player.hand)
        return [
            TurnStartedEvent(turn, self.player.ap, hand_names),
            EnemyIntentTelegraphedEvent(enemy.name, intent.description),
        ]

    def _deal_hand(self) -> None:
        """Draw from the deck, then conjure cards so a full turn of progress is always possible.

        The solver plans a path. Steps are covered by drawn cards when they
        match; otherwise a one-turn conjured copy is added. Steps are covered
        until their total cost would exceed the turn's AP.
        """
        state = self._state
        player = state.player
        deck = list(player.deck)
        discard = list(player.discard)
        hand: list[CardInstance] = list(player.hand)

        for _ in range(self.config.draw_count):
            if not deck:
                if not discard:
                    break
                deck, discard = discard, []
                self._rng.shuffle(deck)
            hand.append(deck.pop())

        next_uid = state.next_uid
        budget = player.max_ap
        unclaimed = list(hand)
        for step in plan_solution(state.enemy.equation):
            if step.cost > budget:
                break
            budget -= step.cost
            match = next((inst for inst in unclaimed if inst.card == step), None)
            if match is not None:
                unclaimed.remove(match)
                continue
            hand.append(CardInstance(next_uid, step, conjured=True))
            next_uid += 1

        self._rng.shuffle(hand)
        self._state = replace(
            state,
            next_uid=next_uid,
            player=replace(player, deck=tuple(deck), hand=tuple(hand), discard=tuple(discard)),
        )
