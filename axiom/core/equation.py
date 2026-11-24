"""Equation wrapper (``lhs = rhs``) and granular, step-by-step transformations.

Nothing here simplifies everything at once. Each transformation does one
algebraic job, so that cards such as *Combine Like Terms* and *Distribute*
each have their own role in play:

* :meth:`Equation.apply_binary_both_sides` applies ``+ - * /`` to both sides
  and only collapses trivial identities (``+4 - 4``, ``3x / 3``, a group
  multiplier divided back out, constant-only arithmetic).
* :meth:`Equation.combine_like_terms` merges constants and like variable terms.
* :meth:`Equation.distribute` expands groups such as ``2(x + 3)``.

The engine assumes equations are **linear** in a single variable, which holds
for everything the generator, cards and enemy intents produce.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

from .ast_nodes import (
    BinaryOperator,
    BinaryOpNode,
    ConstantNode,
    ExprNode,
    GroupNode,
    Number,
    Token,
    VariableNode,
    build_sum,
    flatten_sum,
    format_fraction,
    negate,
    to_fraction,
)

Side = Literal["lhs", "rhs"]


@dataclass(frozen=True, slots=True)
class Cancellation:
    """A term that disappeared because of a trivial identity."""

    side: Side
    term: str


@dataclass(frozen=True, slots=True)
class TransformResult:
    """The output of a transformation plus what it cancelled (for UI events)."""

    equation: Equation
    cancellations: tuple[Cancellation, ...] = ()


@dataclass(frozen=True, slots=True)
class Equation:
    lhs: ExprNode
    rhs: ExprNode

    # ------------------------------------------------------------------ display

    def to_string(self) -> str:
        return f"{self.lhs.to_string()} = {self.rhs.to_string()}"

    def to_tokens(self) -> list[Token]:
        return [*self.lhs.to_tokens(), {"text": " = ", "type": "OPERATOR"}, *self.rhs.to_tokens()]

    def __str__(self) -> str:
        return self.to_string()

    def clone(self) -> Equation:
        return Equation(self.lhs.clone(), self.rhs.clone())

    def side(self, which: Side) -> ExprNode:
        return self.lhs if which == "lhs" else self.rhs

    # --------------------------------------------------------------- validation

    def satisfied_by(self, x_val: Number) -> bool:
        value = to_fraction(x_val)
        return self.lhs.evaluate(value) == self.rhs.evaluate(value)

    def linear_form(self, which: Side) -> tuple[Fraction, Fraction]:
        """Return ``(a, b)`` such that the chosen side equals ``a*x + b``."""
        return linear_form(self.side(which))

    def has_unique_solution(self) -> bool:
        return self.linear_form("lhs")[0] != self.linear_form("rhs")[0]

    def solve_exact(self) -> Fraction | None:
        """Closed-form root of the linear equation (for verification, not gameplay)."""
        a_l, b_l = self.linear_form("lhs")
        a_r, b_r = self.linear_form("rhs")
        if a_l == a_r:
            return None
        return (b_r - b_l) / (a_l - a_r)

    def is_solved(self) -> bool:
        """True if one side is exactly ``x`` and the other a single constant."""
        return _is_isolated(self.lhs, self.rhs) or _is_isolated(self.rhs, self.lhs)

    def get_solution(self) -> Fraction | None:
        if _is_isolated(self.lhs, self.rhs):
            assert isinstance(self.rhs, ConstantNode)
            return self.rhs.value
        if _is_isolated(self.rhs, self.lhs):
            assert isinstance(self.lhs, ConstantNode)
            return self.lhs.value
        return None

    # ----------------------------------------------------------- transformations

    def apply_binary_both_sides(self, op: BinaryOperator, operand: ExprNode) -> Equation:
        return self.transform_binary_both_sides(op, operand).equation

    def transform_binary_both_sides(self, op: BinaryOperator, operand: ExprNode) -> TransformResult:
        """Apply ``op operand`` to both sides, reporting trivial cancellations."""
        new_lhs, lhs_cancelled = _apply_to_side(self.lhs, op, operand)
        new_rhs, rhs_cancelled = _apply_to_side(self.rhs, op, operand)
        cancellations = tuple(
            [Cancellation("lhs", term) for term in lhs_cancelled]
            + [Cancellation("rhs", term) for term in rhs_cancelled]
        )
        return TransformResult(Equation(new_lhs, new_rhs), cancellations)

    def combine_like_terms(self) -> Equation:
        return Equation(combine_like_terms(self.lhs), combine_like_terms(self.rhs))

    def distribute(self) -> Equation:
        return Equation(distribute(self.lhs), distribute(self.rhs))


# ---------------------------------------------------------------------------
# Pure tree functions
# ---------------------------------------------------------------------------


def _is_isolated(candidate: ExprNode, other: ExprNode) -> bool:
    return (
        isinstance(candidate, VariableNode)
        and candidate.coefficient == 1
        and isinstance(other, ConstantNode)
    )


def linear_form(node: ExprNode) -> tuple[Fraction, Fraction]:
    """Return ``(a, b)`` with ``node == a*x + b`` (valid for linear expressions)."""
    b = node.evaluate(Fraction(0))
    a = node.evaluate(Fraction(1)) - b
    return a, b


def _apply_to_side(side: ExprNode, op: BinaryOperator, operand: ExprNode) -> tuple[ExprNode, list[str]]:
    if op in ("+", "-"):
        term = operand if op == "+" else negate(operand)
        return _add_term(side, term)
    if not isinstance(operand, ConstantNode):
        raise ValueError("both sides can only be multiplied or divided by a constant")
    if operand.value == 0:
        raise ValueError("cannot multiply or divide both sides by zero")
    factor = operand.value if op == "*" else 1 / operand.value
    return _scale(side, factor)


def _add_term(side: ExprNode, term: ExprNode) -> tuple[ExprNode, list[str]]:
    if isinstance(term, ConstantNode) and term.value == 0:
        return side, []
    terms = flatten_sum(side)
    inverse = negate(term)
    # Cancel against the most recently added matching term first.
    for index in range(len(terms) - 1, -1, -1):
        if terms[index] == inverse:
            remaining = terms[:index] + terms[index + 1 :]
            return build_sum(remaining), [terms[index].to_string()]
    if isinstance(side, ConstantNode) and isinstance(term, ConstantNode):
        return ConstantNode(side.value + term.value), []
    return build_sum([side, term]), []


def _scale(node: ExprNode, factor: Fraction) -> tuple[ExprNode, list[str]]:
    if factor == 1:
        return node, []
    if isinstance(node, ConstantNode):
        return ConstantNode(node.value * factor), []
    if isinstance(node, VariableNode):
        new_coefficient = node.coefficient * factor
        cancelled = [format_fraction(node.coefficient)] if new_coefficient == 1 else []
        return VariableNode(node.name, new_coefficient), cancelled
    if isinstance(node, GroupNode):
        new_multiplier = node.multiplier * factor
        if new_multiplier == 1:
            return node.inner, [format_fraction(node.multiplier)]
        return GroupNode(node.inner, new_multiplier), []
    if isinstance(node, BinaryOpNode):
        # Undo an explicit product/quotient by a constant: (A / 3) * 3 -> A
        if node.op == "/" and isinstance(node.right, ConstantNode) and node.right.value == factor:
            return node.left, [f"/{format_fraction(node.right.value)}"]
        if node.op == "*" and isinstance(node.left, ConstantNode) and node.left.value * factor == 1:
            return node.right, [format_fraction(node.left.value)]
    return GroupNode(node, factor), []


def combine_like_terms(node: ExprNode) -> ExprNode:
    """Merge constants and like variable terms (recursively inside groups)."""
    if isinstance(node, GroupNode):
        inner = combine_like_terms(node.inner)
        if isinstance(inner, ConstantNode):
            return ConstantNode(inner.value * node.multiplier)
        if isinstance(inner, VariableNode):
            return VariableNode(inner.name, inner.coefficient * node.multiplier)
        return GroupNode(inner, node.multiplier)
    if isinstance(node, BinaryOpNode) and node.op in ("*", "/"):
        return _combine_product(node)
    if isinstance(node, BinaryOpNode):
        return _combine_sum(node)
    return node


def _combine_product(node: BinaryOpNode) -> ExprNode:
    left = combine_like_terms(node.left)
    right = combine_like_terms(node.right)
    if node.op == "*":
        if isinstance(left, ConstantNode) and isinstance(right, ConstantNode):
            return ConstantNode(left.value * right.value)
        if isinstance(left, ConstantNode) and isinstance(right, VariableNode):
            return VariableNode(right.name, right.coefficient * left.value)
        if isinstance(left, VariableNode) and isinstance(right, ConstantNode):
            return VariableNode(left.name, left.coefficient * right.value)
    elif isinstance(right, ConstantNode) and right.value != 0:
        if isinstance(left, ConstantNode):
            return ConstantNode(left.value / right.value)
        if isinstance(left, VariableNode):
            return VariableNode(left.name, left.coefficient / right.value)
    return BinaryOpNode(node.op, left, right)


def _combine_sum(node: ExprNode) -> ExprNode:
    terms = [combine_like_terms(term) for term in flatten_sum(node)]
    # Each slot is either a merged bucket key or a passthrough term; merged
    # buckets keep the position of their first occurrence.
    slots: list[str | ExprNode] = []
    constant_total = Fraction(0)
    variable_totals: dict[str, Fraction] = {}
    for term in terms:
        if isinstance(term, ConstantNode):
            if "#const" not in slots:
                slots.append("#const")
            constant_total += term.value
        elif isinstance(term, VariableNode):
            key = f"#var:{term.name}"
            if key not in slots:
                slots.append(key)
            variable_totals[term.name] = variable_totals.get(term.name, Fraction(0)) + term.coefficient
        else:
            slots.append(term)
    result: list[ExprNode] = []
    for slot in slots:
        if isinstance(slot, ExprNode):
            result.append(slot)
        elif slot == "#const":
            if constant_total != 0:
                result.append(ConstantNode(constant_total))
        else:
            name = slot.removeprefix("#var:")
            coefficient = variable_totals[name]
            if coefficient != 0:
                result.append(VariableNode(name, coefficient))
    return build_sum(result)


def distribute(node: ExprNode) -> ExprNode:
    """Expand every group (and constant product/quotient) into a flat sum."""
    if isinstance(node, GroupNode):
        inner = distribute(node.inner)
        return build_sum([_scale_term(term, node.multiplier) for term in flatten_sum(inner)])
    if isinstance(node, BinaryOpNode):
        if node.op == "*" and isinstance(node.left, ConstantNode):
            return distribute(GroupNode(node.right, node.left.value))
        if node.op == "*" and isinstance(node.right, ConstantNode):
            return distribute(GroupNode(node.left, node.right.value))
        if node.op == "/" and isinstance(node.right, ConstantNode) and node.right.value != 0:
            return distribute(GroupNode(node.left, 1 / node.right.value))
        if node.is_additive():
            expanded: list[ExprNode] = []
            for term in flatten_sum(node):
                expanded.extend(flatten_sum(distribute(term)))
            return build_sum(expanded)
        return BinaryOpNode(node.op, distribute(node.left), distribute(node.right))
    return node


def _scale_term(term: ExprNode, factor: Fraction) -> ExprNode:
    if isinstance(term, ConstantNode):
        return ConstantNode(term.value * factor)
    if isinstance(term, VariableNode):
        return VariableNode(term.name, term.coefficient * factor)
    return BinaryOpNode("*", ConstantNode(factor), term)


def contains_group(node: ExprNode) -> bool:
    if isinstance(node, GroupNode):
        return True
    if isinstance(node, BinaryOpNode):
        return contains_group(node.left) or contains_group(node.right)
    return False
