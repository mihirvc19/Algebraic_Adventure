"""Operation Cards: the player's algebraic moves.

Each card can :meth:`~OperationCard.preview` its effect without side effects
(for hover previews) and :meth:`~OperationCard.execute` it, which returns the
new equation and the events to animate. Cards are immutable value objects:
two cards with the same type and parameters are equal.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from fractions import Fraction

from .ast_nodes import ConstantNode, Number, VariableNode, format_fraction, to_fraction
from .equation import Equation, TransformResult
from .events import (
    CombatEvent,
    EquationMutatedEvent,
    MessyFractionWarningEvent,
    SolutionStrikeEvent,
    TermCancelledEvent,
)


class IllegalCardPlayError(ValueError):
    """Raised when a card is executed on an equation it cannot legally affect."""


class OperationCard(ABC):
    """Base class of every card."""

    __slots__ = ()

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def cost(self) -> int: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def _transform(self, eq: Equation) -> TransformResult: ...

    def unplayable_reason(self, eq: Equation) -> str | None:
        """``None`` if the card may be played on ``eq``, else a human-readable reason."""
        return None

    def can_play(self, eq: Equation) -> bool:
        return self.unplayable_reason(eq) is None

    def preview(self, eq: Equation) -> Equation:
        """Dry run: the equation that would result, with no side effects."""
        return self._transform(eq).equation

    def execute(self, eq: Equation) -> tuple[Equation, list[CombatEvent]]:
        reason = self.unplayable_reason(eq)
        if reason is not None:
            raise IllegalCardPlayError(reason)
        result = self._transform(eq)
        events: list[CombatEvent] = [
            TermCancelledEvent(c.side, c.term) for c in result.cancellations
        ]
        events.extend(self._warnings(eq, result.equation))
        events.append(EquationMutatedEvent(self.name, eq, result.equation))
        return result.equation, events

    def _warnings(self, before: Equation, after: Equation) -> list[CombatEvent]:
        return []

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r}>"


# ---------------------------------------------------------------------------
# Scalar cards
# ---------------------------------------------------------------------------


class _ScalarCard(OperationCard):
    __slots__ = ("_n",)

    def __init__(self, n: Number) -> None:
        value = to_fraction(n)
        if value == 0:
            raise ValueError(f"{type(self).__name__} requires a non-zero value")
        self._n = value

    @property
    def n(self) -> Fraction:
        return self._n

    @property
    def cost(self) -> int:
        return 1

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ScalarCard) and type(self) is type(other) and self._n == other._n

    def __hash__(self) -> int:
        return hash((type(self).__name__, self._n))


class AddConstantCard(_ScalarCard):
    __slots__ = ()

    @property
    def name(self) -> str:
        return f"Add {format_fraction(self.n)}"

    @property
    def description(self) -> str:
        return f"Add {format_fraction(self.n)} to both sides."

    def _transform(self, eq: Equation) -> TransformResult:
        return eq.transform_binary_both_sides("+", ConstantNode(self.n))


class SubtractConstantCard(_ScalarCard):
    __slots__ = ()

    @property
    def name(self) -> str:
        return f"Subtract {format_fraction(self.n)}"

    @property
    def description(self) -> str:
        return f"Subtract {format_fraction(self.n)} from both sides."

    def _transform(self, eq: Equation) -> TransformResult:
        return eq.transform_binary_both_sides("-", ConstantNode(self.n))


class MultiplyCard(_ScalarCard):
    __slots__ = ()

    @property
    def name(self) -> str:
        return f"Multiply by {format_fraction(self.n)}"

    @property
    def description(self) -> str:
        return f"Multiply both sides by {format_fraction(self.n)}."

    def _transform(self, eq: Equation) -> TransformResult:
        return eq.transform_binary_both_sides("*", ConstantNode(self.n))


class DivideCard(_ScalarCard):
    __slots__ = ()

    @property
    def name(self) -> str:
        return f"Divide by {format_fraction(self.n)}"

    @property
    def description(self) -> str:
        return f"Divide both sides by {format_fraction(self.n)}. Uneven division leaves fractions."

    def _transform(self, eq: Equation) -> TransformResult:
        return eq.transform_binary_both_sides("/", ConstantNode(self.n))

    def _warnings(self, before: Equation, after: Equation) -> list[CombatEvent]:
        if self.would_leave_fractions(before):
            return [MessyFractionWarningEvent(self.n, after)]
        return []

    def would_leave_fractions(self, eq: Equation) -> bool:
        """True if some term of ``eq`` is not evenly divisible by ``n``."""
        values = (*eq.linear_form("lhs"), *eq.linear_form("rhs"))
        return any((value / self.n).denominator != 1 for value in values)


class _VariableTermCard(_ScalarCard):
    __slots__ = ()

    def _term(self) -> VariableNode:
        return VariableNode("x", self.n)


class AddVariableCard(_VariableTermCard):
    """Add ``k*x`` to both sides (for equations with x on both sides)."""

    __slots__ = ()

    @property
    def name(self) -> str:
        return f"Add {self._term()}"

    @property
    def description(self) -> str:
        return f"Add {self._term()} to both sides."

    def _transform(self, eq: Equation) -> TransformResult:
        return eq.transform_binary_both_sides("+", self._term())


class SubtractVariableCard(_VariableTermCard):
    """Subtract ``k*x`` from both sides (for equations with x on both sides)."""

    __slots__ = ()

    @property
    def name(self) -> str:
        return f"Subtract {self._term()}"

    @property
    def description(self) -> str:
        return f"Subtract {self._term()} from both sides."

    def _transform(self, eq: Equation) -> TransformResult:
        return eq.transform_binary_both_sides("-", self._term())


# ---------------------------------------------------------------------------
# Utility cards
# ---------------------------------------------------------------------------


class _UtilityCard(OperationCard):
    __slots__ = ()

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other)

    def __hash__(self) -> int:
        return hash(type(self).__name__)

    def unplayable_reason(self, eq: Equation) -> str | None:
        if self.preview(eq).to_string() == eq.to_string():
            return f"{self.name} would not change {eq}"
        return None


class CombineLikeTermsCard(_UtilityCard):
    __slots__ = ()

    @property
    def name(self) -> str:
        return "Combine Like Terms"

    @property
    def cost(self) -> int:
        return 0

    @property
    def description(self) -> str:
        return "Merge constants and like x-terms on each side."

    def _transform(self, eq: Equation) -> TransformResult:
        return TransformResult(eq.combine_like_terms())


class DistributeCard(_UtilityCard):
    __slots__ = ()

    @property
    def name(self) -> str:
        return "Distribute"

    @property
    def cost(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Expand parentheses, e.g. 2(x + 3) becomes 2x + 6."

    def _transform(self, eq: Equation) -> TransformResult:
        return TransformResult(eq.distribute())


class ExecuteSolveCard(_UtilityCard):
    """The finisher: deals fatal damage once x is isolated."""

    __slots__ = ()

    @property
    def name(self) -> str:
        return "Execute Solve"

    @property
    def cost(self) -> int:
        return 1

    @property
    def description(self) -> str:
        return "Fatal strike. Playable only once x stands alone (x = number)."

    def _transform(self, eq: Equation) -> TransformResult:
        return TransformResult(eq)

    def unplayable_reason(self, eq: Equation) -> str | None:
        if not eq.is_solved():
            return f"{eq} is not solved yet; isolate x first"
        return None

    def execute(self, eq: Equation) -> tuple[Equation, list[CombatEvent]]:
        reason = self.unplayable_reason(eq)
        if reason is not None:
            raise IllegalCardPlayError(reason)
        solution = eq.get_solution()
        assert solution is not None
        return eq, [SolutionStrikeEvent(solution)]
