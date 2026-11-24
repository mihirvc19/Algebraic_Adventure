#!/usr/bin/env python3
"""Terminal prototype for the Axiom combat loop.

Fight a run of equation-enemies: read each enemy's equation and intent,
preview and play cards, undo moves, and watch the events print as they happen.

    python cli_demo.py              # interactive
    python cli_demo.py --seed 7     # reproducible run
    python cli_demo.py --auto       # let the built-in solver play (smoke test)
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from typing import Callable

from core.ast_nodes import Token
from core.combat import CombatEngine, IllegalActionError, PlayerState, TurnPhase
from core.equation import Equation
from core.events import (
    ActionUndoneEvent,
    CardPlayedEvent,
    CombatEndedEvent,
    CombatEvent,
    EnemyIntentTelegraphedEvent,
    EnemyIntentTriggeredEvent,
    EquationMutatedEvent,
    MessyFractionWarningEvent,
    PlayerDamagedEvent,
    SolutionStrikeEvent,
    TermCancelledEvent,
    TurnStartedEvent,
)
from core.solver import next_step

ROSTER: tuple[tuple[str, int], ...] = (
    ("Mushroom", 1),
    ("Goblin", 2),
    ("Flying Eye", 2),
    ("Skeleton", 3),
    ("Evil Wizard", 3),
)
HEAL_BETWEEN_FIGHTS = 10

# ------------------------------------------------------------------ rendering

_USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ
_TOKEN_COLORS = {
    "VARIABLE": "\033[96m",
    "CONSTANT": "\033[93m",
    "COEFFICIENT": "\033[95m",
    "OPERATOR": "",
    "PAREN": "\033[90m",
}
_RESET = "\033[0m"


def paint(text: str, code: str) -> str:
    return f"{code}{text}{_RESET}" if _USE_COLOR and code else text


def render_tokens(tokens: list[Token]) -> str:
    return "".join(paint(token["text"], _TOKEN_COLORS[token["type"]]) for token in tokens)


def render_equation(eq: Equation) -> str:
    return render_tokens(eq.to_tokens())


def describe_event(event: CombatEvent) -> str | None:
    if isinstance(event, TurnStartedEvent):
        return f"Turn {event.turn} begins ({event.ap} AP)."
    if isinstance(event, EnemyIntentTelegraphedEvent):
        return f"{event.enemy_name} intends to: {event.intent}"
    if isinstance(event, CardPlayedEvent):
        return f"You play {event.card_name} (-{event.ap_spent} AP, {event.ap_remaining} left)."
    if isinstance(event, TermCancelledEvent):
        return f"  * {event.term} cancels out on the {event.side.upper()}"
    if isinstance(event, MessyFractionWarningEvent):
        return f"  ! Uneven division by {event.divisor}: fractions appear."
    if isinstance(event, EquationMutatedEvent):
        return f"  {render_equation(event.before)}  ->  {render_equation(event.after)}"
    if isinstance(event, SolutionStrikeEvent):
        return paint(f"  EXECUTE! x = {event.solution}. A fatal strike!", "\033[92m")
    if isinstance(event, ActionUndoneEvent):
        return f"Undid {event.card_name}. Equation restored to {render_equation(event.restored)}"
    if isinstance(event, EnemyIntentTriggeredEvent):
        return f"{event.enemy_name} uses {event.intent}!"
    if isinstance(event, PlayerDamagedEvent):
        return paint(f"  You take {event.amount} damage ({event.hp_remaining} HP left).", "\033[91m")
    if isinstance(event, CombatEndedEvent):
        return "Victory!" if event.victory else "Defeat..."
    return None


def print_events(events: list[CombatEvent]) -> None:
    for event in events:
        line = describe_event(event)
        if line is not None:
            print(line)


def print_status(engine: CombatEngine, index: int, total: int) -> None:
    enemy = engine.enemy
    player = engine.player
    intent = enemy.intent.description if enemy.intent else "-"
    print()
    print(f"=== Enemy {index}/{total}: {enemy.name} (Tier {enemy.tier}) | Turn {engine.state.turn} ===")
    print(f"  Equation : {render_equation(enemy.equation)}")
    print(f"  Intent   : {intent}")
    print(
        f"  You      : HP {player.hp}/{player.max_hp} | AP {player.ap}/{player.max_ap} | "
        f"Deck {len(player.deck)} | Discard {len(player.discard)}"
    )
    print("  Hand:")
    print_hand(engine, player)


def print_hand(engine: CombatEngine, player: PlayerState) -> None:
    for i, instance in enumerate(player.hand, start=1):
        card = instance.card
        marker = " *conjured" if instance.conjured else ""
        dim = "" if engine.can_play(i - 1) else "  (unplayable)"
        print(f"    [{i}] {card.name:<20} {card.cost} AP  {card.description}{marker}{dim}")


HELP = (
    "Commands: <n> play card n | p <n> preview | u undo | e end turn | "
    "s status | hint | h help | q quit"
)

# --------------------------------------------------------------------- input

InputFn = Callable[[str], str]


def parse_index(text: str, engine: CombatEngine) -> int:
    value = int(text) - 1
    if not 0 <= value < len(engine.player.hand):
        raise IllegalActionError(f"choose a card between 1 and {len(engine.player.hand)}")
    return value


def interactive_turn(engine: CombatEngine, index: int, total: int, read: InputFn) -> bool:
    """Run one player turn. Returns False if the player quits."""
    show_status = True
    while engine.phase is TurnPhase.PLAYER_TURN:
        if show_status:
            print_status(engine, index, total)
            show_status = False
        try:
            raw = read("> ").strip().lower()
        except EOFError:
            return False
        if not raw:
            continue
        try:
            if raw in ("q", "quit"):
                return False
            if raw in ("h", "help", "?"):
                print(HELP)
            elif raw in ("u", "undo"):
                print_events(engine.undo_last_action())
                show_status = True
            elif raw in ("e", "end"):
                print_events(engine.end_turn())
                return True
            elif raw == "hint":
                step = next_step(engine.enemy.equation)
                print(f"Hint: try {step.name}." if step else "No hint available.")
            elif raw.startswith("p"):
                card_index = parse_index(raw[1:].strip(), engine)
                card = engine.player.hand[card_index].card
                print(f"Preview {card.name}: {render_equation(engine.preview_card(card_index))}")
                reason = engine.unplayable_reason(card_index)
                if reason:
                    print(f"  (cannot play now: {reason})")
            elif raw in ("s", "status"):
                show_status = True
            else:
                print_events(engine.play_card(parse_index(raw, engine)))
                show_status = True
        except IllegalActionError as error:
            print(f"Not allowed: {error}")
        except ValueError:
            print(f"Unknown command. {HELP}")
    return True


def auto_turn(engine: CombatEngine, index: int, total: int) -> bool:
    """Let the solver play: use recommended cards from hand, then end the turn."""
    print_status(engine, index, total)
    while engine.phase is TurnPhase.PLAYER_TURN:
        step = next_step(engine.enemy.equation)
        choice = next(
            (
                i
                for i, inst in enumerate(engine.player.hand)
                if inst.card == step and engine.can_play(i)
            ),
            None,
        )
        if choice is None:
            print("> e")
            print_events(engine.end_turn())
            return True
        print(f"> {choice + 1}")
        print_events(engine.play_card(choice))
    return True


# ----------------------------------------------------------------------- run


def run(seed: int | None, auto: bool, enemies: int, read: InputFn = input) -> int:
    master = random.Random(seed)
    roster = ROSTER[:enemies]
    hp: int | None = None
    print("AXIOM: the Algebraic Tactical RPG")
    print("Solve each enemy's equation, then play Execute Solve to defeat it.")
    print(HELP)
    for number, (name, tier) in enumerate(roster, start=1):
        engine = CombatEngine.from_generator(name, tier, seed=master.randrange(2**31), player_hp=hp)
        print(f"\nA wild {name} appears!")
        print_events(engine.start())
        while not engine.is_over:
            keep_going = (
                auto_turn(engine, number, len(roster))
                if auto
                else interactive_turn(engine, number, len(roster), read)
            )
            if not keep_going:
                print("You flee the dungeon. Goodbye!")
                return 1
        if engine.phase is TurnPhase.DEFEAT:
            print(f"\nYou were defeated by the {name}. Run over.")
            return 2
        hp = min(engine.player.max_hp, engine.player.hp + HEAL_BETWEEN_FIGHTS)
        print(f"You rest and recover to {hp} HP.")
    print("\nThe dungeon is cleared. Every equation is solved!")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seed", type=int, default=None, help="seed for a reproducible run")
    parser.add_argument("--auto", action="store_true", help="let the solver play (non-interactive)")
    parser.add_argument(
        "--enemies", type=int, default=len(ROSTER), choices=range(1, len(ROSTER) + 1),
        help="number of enemies in the run",
    )
    args = parser.parse_args(argv)
    return run(args.seed, args.auto, args.enemies)


if __name__ == "__main__":
    sys.exit(main())
