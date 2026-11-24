from fractions import Fraction

import pytest

from core.ast_nodes import add, const, group, var
from core.cards import (
    AddConstantCard,
    AddVariableCard,
    CombineLikeTermsCard,
    DistributeCard,
    DivideCard,
    ExecuteSolveCard,
    IllegalCardPlayError,
    MultiplyCard,
    SubtractConstantCard,
    SubtractVariableCard,
)
from core.equation import Equation
from core.events import (
    EquationMutatedEvent,
    MessyFractionWarningEvent,
    SolutionStrikeEvent,
    TermCancelledEvent,
)
from core.solver import next_step, plan_solution


def test_preview_is_non_destructive_and_matches_execute() -> None:
    eq = Equation(add(var(3), const(4)), const(19))
    card = SubtractConstantCard(4)
    preview = card.preview(eq)
    assert eq.to_string() == "3x + 4 = 19"
    result, events = card.execute(eq)
    assert preview == result
    assert result.to_string() == "3x = 15"
    assert TermCancelledEvent("lhs", "4") in events
    assert isinstance(events[-1], EquationMutatedEvent)
    assert events[-1].before == eq and events[-1].after == result


def test_messy_fraction_warning() -> None:
    eq = Equation(add(var(3), const(1)), const(7))
    _, events = DivideCard(2).execute(eq)
    warnings = [e for e in events if isinstance(e, MessyFractionWarningEvent)]
    assert len(warnings) == 1 and warnings[0].divisor == 2

    _, clean_events = DivideCard(2).execute(Equation(add(var(4), const(2)), const(10)))
    assert not any(isinstance(e, MessyFractionWarningEvent) for e in clean_events)


def test_execute_solve_requires_solved_equation() -> None:
    with pytest.raises(IllegalCardPlayError):
        ExecuteSolveCard().execute(Equation(var(2), const(6)))
    eq, events = ExecuteSolveCard().execute(Equation(var(), const(3)))
    assert events == [SolutionStrikeEvent(Fraction(3))]


def test_utility_cards_need_something_to_do() -> None:
    plain = Equation(add(var(3), const(4)), const(19))
    assert not CombineLikeTermsCard().can_play(plain)
    assert not DistributeCard().can_play(plain)
    with pytest.raises(IllegalCardPlayError):
        DistributeCard().execute(plain)
    grouped = Equation(group(add(var(), const(3)), 2), const(14))
    assert DistributeCard().preview(grouped).to_string() == "2x + 6 = 14"


def test_variable_cards() -> None:
    eq = Equation(add(var(5), const(2)), add(var(2), const(11)))
    assert SubtractVariableCard(2).preview(eq).to_string() == "5x + 2 - 2x = 11"
    assert AddVariableCard(1).name == "Add x"
    assert SubtractVariableCard(2).name == "Subtract 2x"


def test_card_value_semantics() -> None:
    assert DivideCard(3) == DivideCard(3)
    assert DivideCard(3) != MultiplyCard(3)
    assert AddConstantCard(2) != SubtractConstantCard(2)
    assert ExecuteSolveCard() == ExecuteSolveCard()
    assert len({DivideCard(3), DivideCard(3), CombineLikeTermsCard()}) == 2
    assert DivideCard(Fraction(3, 2)).name == "Divide by 3/2"
    with pytest.raises(ValueError):
        DivideCard(0)
    with pytest.raises(ValueError):
        AddConstantCard(0)


def test_costs() -> None:
    assert CombineLikeTermsCard().cost == 0
    assert DistributeCard().cost == 1
    assert ExecuteSolveCard().cost == 1
    assert AddConstantCard(4).cost == 1


def test_solver_plans() -> None:
    eq = Equation(add(group(add(var(), const(3)), 2), const(4)), const(20))
    assert [c.name for c in plan_solution(eq)] == [
        "Subtract 4",
        "Divide by 2",
        "Subtract 3",
        "Execute Solve",
    ]
    both = Equation(add(var(5), const(2)), add(var(2), const(11)))
    assert [c.name for c in plan_solution(both)] == [
        "Subtract 2x",
        "Combine Like Terms",
        "Subtract 2",
        "Divide by 3",
        "Execute Solve",
    ]
    # Group whose multiplier doesn't divide the other side: distribute instead.
    messy = Equation(group(add(var(), const(1)), 2), const(5))
    assert next_step(messy) == DistributeCard()
    # Fractional coefficient: multiply it away.
    assert next_step(Equation(var(Fraction(2, 3)), const(4))) == MultiplyCard(3)
    # x on the right-hand side.
    assert [c.name for c in plan_solution(Equation(const(9), add(var(), const(4))))] == [
        "Subtract 4",
        "Execute Solve",
    ]
    # No unique solution.
    assert plan_solution(Equation(add(var(2), const(1)), add(var(2), const(3)))) == []
