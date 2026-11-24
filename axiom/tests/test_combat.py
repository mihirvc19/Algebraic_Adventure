import random
from fractions import Fraction

import pytest

from core.ast_nodes import add, const, group, var
from core.cards import DistributeCard, ExecuteSolveCard, SubtractConstantCard
from core.combat import (
    CombatConfig,
    CombatEngine,
    EnemyState,
    IllegalActionError,
    Intent,
    TurnPhase,
)
from core.equation import Equation
from core.events import (
    ActionUndoneEvent,
    CombatEndedEvent,
    CombatEvent,
    EnemyIntentTelegraphedEvent,
    EnemyIntentTriggeredEvent,
    EquationMutatedEvent,
    PlayerDamagedEvent,
    SolutionStrikeEvent,
    TurnStartedEvent,
)
from core.solver import next_step


def always(intent: Intent):  # type: ignore[no-untyped-def]
    def policy(enemy: EnemyState, rng: random.Random, config: CombatConfig) -> Intent:
        return intent

    return policy


def two_step_engine(**kwargs: object) -> CombatEngine:
    eq = Equation(add(var(3), const(4)), const(19))  # x = 5
    return CombatEngine("Goblin", eq, 5, tier=2, seed=1, **kwargs)  # type: ignore[arg-type]


def find_card(engine: CombatEngine, name: str) -> int:
    for index, instance in enumerate(engine.player.hand):
        if instance.card.name == name:
            return index
    raise AssertionError(f"{name} not in hand: {[i.card.name for i in engine.player.hand]}")


def play_turn_with_solver(engine: CombatEngine) -> list[CombatEvent]:
    """Play solver-recommended cards from hand until none is available, then return."""
    events: list[CombatEvent] = []
    while engine.phase is TurnPhase.PLAYER_TURN:
        step = next_step(engine.enemy.equation)
        index = next(
            (
                i
                for i, inst in enumerate(engine.player.hand)
                if inst.card == step and engine.can_play(i)
            ),
            None,
        )
        if index is None:
            break
        events.extend(engine.play_card(index))
    return events


def autoplay(engine: CombatEngine, max_turns: int = 30) -> list[CombatEvent]:
    events = engine.start()
    for _ in range(max_turns):
        events.extend(play_turn_with_solver(engine))
        if engine.is_over:
            break
        events.extend(engine.end_turn())
        if engine.is_over:
            break
    return events


# ------------------------------------------------------------------ lifecycle


def test_start_deals_hand_and_telegraphs_intent() -> None:
    engine = two_step_engine()
    assert engine.phase is TurnPhase.SETUP
    events = engine.start()
    assert engine.phase is TurnPhase.PLAYER_TURN
    assert isinstance(events[0], TurnStartedEvent) and events[0].turn == 1
    assert isinstance(events[1], EnemyIntentTelegraphedEvent)
    assert engine.enemy.intent is not None
    assert engine.player.ap == engine.player.max_ap == 3
    assert len(engine.player.hand) >= 3
    with pytest.raises(IllegalActionError):
        engine.start()


def test_actions_rejected_before_start() -> None:
    engine = two_step_engine()
    with pytest.raises(IllegalActionError):
        engine.play_card(0)
    with pytest.raises(IllegalActionError):
        engine.end_turn()


def test_hand_always_offers_a_full_turn_of_progress() -> None:
    # Tier 1 and 2 enemies can always be beaten on turn 1 with the dealt hand.
    for seed in range(150):
        tier = seed % 2 + 1
        engine = CombatEngine.from_generator("Dummy", tier, seed=seed)
        engine.start()
        play_turn_with_solver(engine)
        assert engine.phase is TurnPhase.VICTORY, f"seed {seed}: {engine.enemy.equation}"


@pytest.mark.parametrize("seed", range(40))
def test_tier3_autoplay_reaches_victory(seed: int) -> None:
    engine = CombatEngine.from_generator("Skeleton", 3, seed=seed)
    events = autoplay(engine)
    assert engine.phase is TurnPhase.VICTORY, engine.enemy.equation
    assert isinstance(events[-1], CombatEndedEvent) and events[-1].victory
    strikes = [e for e in events if isinstance(e, SolutionStrikeEvent)]
    assert strikes == [SolutionStrikeEvent(Fraction(engine.enemy.root))]


def test_same_seed_replays_identically() -> None:
    first = autoplay(CombatEngine.from_generator("Wizard", 3, seed=99))
    second = autoplay(CombatEngine.from_generator("Wizard", 3, seed=99))
    assert first == second


# ---------------------------------------------------------------- card plays


def test_play_card_updates_equation_ap_and_zones() -> None:
    engine = two_step_engine(intent_policy=always(Intent("ATTACK", 5)))
    engine.start()
    hand_before = len(engine.player.hand)
    index = find_card(engine, "Subtract 4")
    events = engine.play_card(index)
    assert engine.enemy.equation.to_string() == "3x = 15"
    assert engine.player.ap == 2
    assert len(engine.player.hand) == hand_before - 1
    assert any(isinstance(e, EquationMutatedEvent) for e in events)


def test_illegal_plays_are_rejected_without_changing_state() -> None:
    engine = two_step_engine()
    engine.start()
    snapshot = engine.state
    with pytest.raises(IllegalActionError):
        engine.play_card(find_card(engine, "Execute Solve"))
    with pytest.raises(IllegalActionError):
        engine.play_card(99)
    assert engine.state == snapshot


def test_ap_limits_plays() -> None:
    engine = two_step_engine(config=CombatConfig(max_ap=1))
    engine.start()
    engine.play_card(find_card(engine, "Subtract 4"))
    assert engine.player.ap == 0
    costly = next(i for i, inst in enumerate(engine.player.hand) if inst.card.cost > 0)
    assert "AP" in (engine.unplayable_reason(costly) or "")
    with pytest.raises(IllegalActionError):
        engine.play_card(costly)


def test_preview_does_not_change_state() -> None:
    engine = two_step_engine()
    engine.start()
    snapshot = engine.state
    preview = engine.preview_card(find_card(engine, "Subtract 4"))
    assert preview.to_string() == "3x = 15"
    assert engine.state == snapshot


def test_victory_ends_combat() -> None:
    engine = CombatEngine("Slime", Equation(add(var(), const(2)), const(5)), 3, seed=3)
    engine.start()
    engine.play_card(find_card(engine, "Subtract 2"))
    events = engine.play_card(find_card(engine, "Execute Solve"))
    assert engine.phase is TurnPhase.VICTORY
    assert events[-1] == CombatEndedEvent(victory=True, turns=1)
    assert not engine.can_undo
    with pytest.raises(IllegalActionError):
        engine.end_turn()
    with pytest.raises(IllegalActionError):
        engine.undo_last_action()


# --------------------------------------------------------------------- undo


def test_undo_restores_exact_previous_state() -> None:
    engine = two_step_engine()
    engine.start()
    start_state = engine.state
    engine.play_card(find_card(engine, "Subtract 4"))
    after_first = engine.state
    engine.play_card(find_card(engine, "Divide by 3"))
    assert engine.enemy.equation.to_string() == "x = 5"

    events = engine.undo_last_action()
    assert events == [ActionUndoneEvent("Divide by 3", after_first.enemy.equation)]
    assert engine.state == after_first

    engine.undo_last_action()
    assert engine.state == start_state
    assert engine.player.ap == 3
    assert engine.enemy.equation.to_string() == "3x + 4 = 19"
    assert not engine.can_undo
    with pytest.raises(IllegalActionError):
        engine.undo_last_action()


def test_undo_then_replay_different_card() -> None:
    engine = CombatEngine(
        "Imp",
        Equation(group(add(var(), const(3)), 2), const(14)),
        4,
        tier=3,
        seed=5,
        deck=[DistributeCard()] * 3,
    )
    engine.start()
    engine.play_card(find_card(engine, "Divide by 2"))
    assert engine.enemy.equation.to_string() == "x + 3 = 7"
    engine.undo_last_action()
    engine.play_card(find_card(engine, "Distribute"))
    assert engine.enemy.equation.to_string() == "2x + 6 = 14"


def test_undo_is_cleared_at_end_of_turn() -> None:
    engine = two_step_engine(intent_policy=always(Intent("ATTACK", 1)))
    engine.start()
    engine.play_card(find_card(engine, "Subtract 4"))
    assert engine.can_undo
    engine.end_turn()
    assert not engine.can_undo
    with pytest.raises(IllegalActionError):
        engine.undo_last_action()
    assert engine.enemy.equation.to_string() == "3x = 15"


# ------------------------------------------------------------- enemy intents


def test_attack_intent_damages_player() -> None:
    engine = two_step_engine(intent_policy=always(Intent("ATTACK", 7)))
    engine.start()
    events = engine.end_turn()
    assert EnemyIntentTriggeredEvent("Goblin", "Attack 7", "ATTACK", 7) in events
    assert PlayerDamagedEvent(7, 43) in events
    assert engine.player.hp == 43
    assert engine.phase is TurnPhase.PLAYER_TURN
    assert engine.state.turn == 2


def test_lethal_attack_causes_defeat() -> None:
    engine = two_step_engine(intent_policy=always(Intent("ATTACK", 10)), player_hp=10)
    engine.start()
    events = engine.end_turn()
    assert engine.phase is TurnPhase.DEFEAT
    assert engine.player.hp == 0
    assert events[-1] == CombatEndedEvent(victory=False, turns=1)
    with pytest.raises(IllegalActionError):
        engine.play_card(0)


def test_reinforce_and_fortify_mutate_equation_but_keep_root() -> None:
    engine = two_step_engine(intent_policy=always(Intent("REINFORCE", 5)))
    engine.start()
    events = engine.end_turn()
    assert engine.enemy.equation.to_string() == "3x + 4 + 5 = 24"
    assert engine.enemy.equation.satisfied_by(5)
    assert any(isinstance(e, EquationMutatedEvent) and e.source == "Goblin" for e in events)

    fortified = two_step_engine(intent_policy=always(Intent("FORTIFY", 2)))
    fortified.start()
    fortified.end_turn()
    assert fortified.enemy.equation.to_string() == "2(3x + 4) = 38"
    # The new hand adapts to the mutated equation.
    play_turn_with_solver(fortified)
    assert fortified.enemy.equation.to_string() == "x = 5"


def test_default_intents_are_telegraphed_descriptions() -> None:
    assert Intent("ATTACK", 8).description == "Attack 8"
    assert Intent("REINFORCE", 5).description == "Reinforce +5"
    assert Intent("FORTIFY", 2).description == "Fortify x2"


# --------------------------------------------------------------- card zones


def test_conjured_cards_vanish_and_deck_cards_cycle() -> None:
    engine = two_step_engine(intent_policy=always(Intent("ATTACK", 1)))
    engine.start()
    total_owned = len(engine.player.deck) + len(engine.player.discard) + sum(
        1 for inst in engine.player.hand if not inst.conjured
    )
    for _ in range(6):
        engine.end_turn()
        owned = len(engine.player.deck) + len(engine.player.discard) + sum(
            1 for inst in engine.player.hand if not inst.conjured
        )
        assert owned == total_owned == 10
        assert all(not inst.conjured for inst in engine.player.discard)


def test_conjured_card_play_and_undo() -> None:
    engine = CombatEngine(
        "Bat",
        Equation(add(var(), const(11)), const(4)),
        -7,
        seed=2,
        deck=[ExecuteSolveCard()] * 3,
    )
    engine.start()
    index = find_card(engine, "Subtract 11")
    assert engine.player.hand[index].conjured
    assert engine.player.hand[index].card == SubtractConstantCard(11)
    engine.play_card(index)
    assert all(inst.card.name != "Subtract 11" for inst in engine.player.hand)
    assert all(inst.card.name != "Subtract 11" for inst in engine.player.discard)
    engine.undo_last_action()
    assert engine.player.hand[index].card.name == "Subtract 11"
