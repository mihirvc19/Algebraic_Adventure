"""Deterministic step-by-step solver expressed as Operation Cards.

The combat engine uses it to make sure the player always holds a workable
path (contextual card generation). It also powers hints, auto-play and tests.
The strategy is the classroom one: tidy up, gather x-terms on one side, peel
off constants, then divide out the coefficient.
"""

from __future__ import annotations

from fractions import Fraction

from .ast_nodes import ConstantNode, ExprNode, GroupNode, VariableNode, flatten_sum
from .cards import (
    AddConstantCard,
    AddVariableCard,
    CombineLikeTermsCard,
    DistributeCard,
    DivideCard,
    ExecuteSolveCard,
    MultiplyCard,
    OperationCard,
    SubtractConstantCard,
    SubtractVariableCard,
)
from .equation import Equation, combine_like_terms, contains_group, linear_form

DEFAULT_MAX_STEPS = 32


def next_step(eq: Equation) -> OperationCard | None:
    """The single best next card for ``eq``, or ``None`` if it can't be solved."""
    if eq.is_solved():
        return ExecuteSolveCard()
    if _combine_changes(eq.lhs) or _combine_changes(eq.rhs):
        return CombineLikeTermsCard()

    a_lhs, _ = linear_form(eq.lhs)
    a_rhs, _ = linear_form(eq.rhs)
    if a_lhs == 0 and a_rhs == 0:
        return None
    if a_lhs != 0 and a_rhs != 0:
        if a_lhs == a_rhs:
            return None  # no unique solution
        if contains_group(eq.lhs) or contains_group(eq.rhs):
            return DistributeCard()
        # Clear x from the side with the smaller coefficient so the survivor stays positive.
        k = a_rhs if a_rhs < a_lhs else a_lhs
        return SubtractVariableCard(k) if k > 0 else AddVariableCard(-k)

    variable_side, constant_side = (eq.lhs, eq.rhs) if a_lhs != 0 else (eq.rhs, eq.lhs)
    if not isinstance(constant_side, ConstantNode):
        return DistributeCard() if contains_group(constant_side) else None

    terms = flatten_sum(variable_side)
    if len(terms) > 1:
        constants = [term for term in terms if isinstance(term, ConstantNode)]
        if constants:
            c = constants[-1].value
            return SubtractConstantCard(c) if c > 0 else AddConstantCard(-c)
        return DistributeCard() if contains_group(variable_side) else None

    (term,) = terms
    if isinstance(term, VariableNode):
        return _isolate_coefficient(term.coefficient)
    if isinstance(term, GroupNode):
        m = term.multiplier
        if m.denominator != 1:
            return MultiplyCard(m.denominator)
        if (constant_side.value / m).denominator == 1:
            return DivideCard(m)
        return DistributeCard()
    return DistributeCard()


def _isolate_coefficient(k: Fraction) -> OperationCard:
    if k.denominator != 1:
        return MultiplyCard(k.denominator)
    return DivideCard(k)


def _combine_changes(side: ExprNode) -> bool:
    return combine_like_terms(side).to_string() != side.to_string()


def plan_solution(eq: Equation, max_steps: int = DEFAULT_MAX_STEPS) -> list[OperationCard]:
    """Full card sequence that solves ``eq``, ending in :class:`ExecuteSolveCard`.

    If the solver gets stuck, it returns the steps it found so far.
    """
    steps: list[OperationCard] = []
    current = eq
    for _ in range(max_steps):
        card = next_step(current)
        if card is None:
            break
        steps.append(card)
        if isinstance(card, ExecuteSolveCard):
            break
        current = card.preview(current)
    return steps
