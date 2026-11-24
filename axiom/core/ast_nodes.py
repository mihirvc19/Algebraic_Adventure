"""Symbolic expression tree for single-variable linear algebra.

Every node is an immutable value object (a frozen dataclass). Transformations
never mutate a tree in place; they build and return a new one. That keeps the
engine deterministic and maps directly onto a C++ port that uses
``std::shared_ptr<const ExprNode>`` with structural equality.

All numbers are ``fractions.Fraction`` so that messy divisions such as ``4/3``
stay exact instead of turning into floating-point approximations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal, Sequence, TypedDict, Union

BinaryOperator = Literal["+", "-", "*", "/"]
TokenType = Literal["VARIABLE", "CONSTANT", "COEFFICIENT", "OPERATOR", "PAREN"]
Number = Union[int, Fraction]

_VALID_OPERATORS: frozenset[str] = frozenset({"+", "-", "*", "/"})


class Token(TypedDict):
    """One renderable chunk of an expression, tagged so a UI can colour-code it.

    Joining every token's ``text`` gives exactly ``ExprNode.to_string()``.
    """

    text: str
    type: TokenType


def to_fraction(value: Number) -> Fraction:
    """Convert an int or Fraction to a Fraction (bools are rejected)."""
    if isinstance(value, bool):
        raise TypeError("booleans are not valid numeric values")
    if isinstance(value, Fraction):
        return value
    if isinstance(value, int):
        return Fraction(value)
    raise TypeError(f"expected int or Fraction, got {type(value).__name__}")


def format_fraction(value: Fraction) -> str:
    """Format a Fraction as ``"3"``, ``"-3"`` or ``"4/3"``."""
    return str(value)


def _tok(text: str, token_type: TokenType) -> Token:
    return {"text": text, "type": token_type}


def _coefficient_tokens(coefficient: Fraction) -> tuple[list[Token], list[Token]]:
    """Split a coefficient into prefix/suffix tokens around a variable or group.

    ``3 -> ("3", "")``, ``-1 -> ("-", "")``, ``2/3 -> ("2", "/3")``,
    ``-1/3 -> ("-", "/3")``.
    """
    numerator = coefficient.numerator
    denominator = coefficient.denominator
    prefix: list[Token] = []
    if numerator == -1:
        prefix.append(_tok("-", "COEFFICIENT"))
    elif numerator != 1:
        prefix.append(_tok(str(numerator), "COEFFICIENT"))
    suffix: list[Token] = []
    if denominator != 1:
        suffix.append(_tok(f"/{denominator}", "COEFFICIENT"))
    return prefix, suffix


class ExprNode(ABC):
    """Base class of every expression node."""

    __slots__ = ()

    @abstractmethod
    def evaluate(self, x_val: Fraction) -> Fraction:
        """Evaluate the expression with the variable bound to ``x_val``."""

    @abstractmethod
    def to_tokens(self) -> list[Token]:
        """Render to tagged tokens for UI colour-coding."""

    @abstractmethod
    def clone(self) -> ExprNode:
        """Return a deep, structurally equal copy of this tree."""

    @abstractmethod
    def contains_variable(self) -> bool:
        """True if any variable term appears in this subtree."""

    def to_string(self) -> str:
        """Clean algebraic formatting, e.g. ``3x + 4`` or ``2(x - 3)``."""
        return "".join(token["text"] for token in self.to_tokens())

    def __str__(self) -> str:
        return self.to_string()


@dataclass(frozen=True, slots=True)
class ConstantNode(ExprNode):
    """An exact rational constant."""

    value: Fraction

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", to_fraction(self.value))

    def evaluate(self, x_val: Fraction) -> Fraction:
        return self.value

    def to_tokens(self) -> list[Token]:
        return [_tok(format_fraction(self.value), "CONSTANT")]

    def clone(self) -> ConstantNode:
        return ConstantNode(self.value)

    def contains_variable(self) -> bool:
        return False


@dataclass(frozen=True, slots=True)
class VariableNode(ExprNode):
    """A variable term with a rational coefficient, e.g. ``3x`` or ``-x/2``."""

    name: str = "x"
    coefficient: Fraction = field(default=Fraction(1))

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("variable name must be non-empty")
        object.__setattr__(self, "coefficient", to_fraction(self.coefficient))

    def evaluate(self, x_val: Fraction) -> Fraction:
        # The engine models single-variable equations; every variable binds to x_val.
        return self.coefficient * x_val

    def to_tokens(self) -> list[Token]:
        prefix, suffix = _coefficient_tokens(self.coefficient)
        return [*prefix, _tok(self.name, "VARIABLE"), *suffix]

    def clone(self) -> VariableNode:
        return VariableNode(self.name, self.coefficient)

    def contains_variable(self) -> bool:
        return True


@dataclass(frozen=True, slots=True)
class BinaryOpNode(ExprNode):
    """A binary operation ``left op right``."""

    op: BinaryOperator
    left: ExprNode
    right: ExprNode

    def __post_init__(self) -> None:
        if self.op not in _VALID_OPERATORS:
            raise ValueError(f"unknown operator {self.op!r}")

    def evaluate(self, x_val: Fraction) -> Fraction:
        lhs = self.left.evaluate(x_val)
        rhs = self.right.evaluate(x_val)
        if self.op == "+":
            return lhs + rhs
        if self.op == "-":
            return lhs - rhs
        if self.op == "*":
            return lhs * rhs
        if rhs == 0:
            raise ZeroDivisionError(f"division by zero while evaluating {self}")
        return lhs / rhs

    def is_additive(self) -> bool:
        return self.op in ("+", "-")

    def to_tokens(self) -> list[Token]:
        if self.is_additive():
            return self._additive_tokens()
        if self.op == "*":
            return self._product_tokens()
        return self._quotient_tokens()

    def _additive_tokens(self) -> list[Token]:
        tokens = self.left.to_tokens()
        magnitude = absolute_if_negative(self.right)
        if magnitude is not None:
            symbol = "-" if self.op == "+" else "+"
            operand = magnitude
        else:
            symbol = self.op
            operand = self.right
        tokens.append(_tok(f" {symbol} ", "OPERATOR"))
        tokens.extend(_wrapped_tokens(operand) if _is_additive(operand) else operand.to_tokens())
        return tokens

    def _product_tokens(self) -> list[Token]:
        right_opens_paren = _is_additive(self.right) or (
            isinstance(self.right, GroupNode) and self.right.multiplier == 1
        )
        if (
            isinstance(self.left, ConstantNode)
            and self.left.value.denominator == 1
            and right_opens_paren
        ):
            # Juxtapose: 3(x + 2)
            left_tokens = self.left.to_tokens()
            for token in left_tokens:
                token["type"] = "COEFFICIENT"
            right_tokens = (
                _wrapped_tokens(self.right) if _is_additive(self.right) else self.right.to_tokens()
            )
            return [*left_tokens, *right_tokens]
        left_tokens = _wrapped_tokens(self.left) if _is_additive(self.left) else self.left.to_tokens()
        right_needs_wrap = _is_additive(self.right) or absolute_if_negative(self.right) is not None
        right_tokens = _wrapped_tokens(self.right) if right_needs_wrap else self.right.to_tokens()
        return [*left_tokens, _tok(" * ", "OPERATOR"), *right_tokens]

    def _quotient_tokens(self) -> list[Token]:
        left_tokens = _wrapped_tokens(self.left) if _is_additive(self.left) else self.left.to_tokens()
        right_needs_wrap = (
            isinstance(self.right, BinaryOpNode)
            or absolute_if_negative(self.right) is not None
            or (isinstance(self.right, ConstantNode) and self.right.value.denominator != 1)
            or (isinstance(self.right, VariableNode) and self.right.coefficient.denominator != 1)
        )
        right_tokens = _wrapped_tokens(self.right) if right_needs_wrap else self.right.to_tokens()
        return [*left_tokens, _tok(" / ", "OPERATOR"), *right_tokens]

    def clone(self) -> BinaryOpNode:
        return BinaryOpNode(self.op, self.left.clone(), self.right.clone())

    def contains_variable(self) -> bool:
        return self.left.contains_variable() or self.right.contains_variable()


@dataclass(frozen=True, slots=True)
class GroupNode(ExprNode):
    """A parenthesised sub-expression with a rational multiplier, e.g. ``2(x + 3)``."""

    inner: ExprNode
    multiplier: Fraction = field(default=Fraction(1))

    def __post_init__(self) -> None:
        object.__setattr__(self, "multiplier", to_fraction(self.multiplier))

    def evaluate(self, x_val: Fraction) -> Fraction:
        return self.multiplier * self.inner.evaluate(x_val)

    def to_tokens(self) -> list[Token]:
        prefix, suffix = _coefficient_tokens(self.multiplier)
        return [*prefix, *_wrapped_tokens(self.inner), *suffix]

    def clone(self) -> GroupNode:
        return GroupNode(self.inner.clone(), self.multiplier)

    def contains_variable(self) -> bool:
        return self.inner.contains_variable()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _is_additive(node: ExprNode) -> bool:
    return isinstance(node, BinaryOpNode) and node.is_additive()


def _wrapped_tokens(node: ExprNode) -> list[Token]:
    return [_tok("(", "PAREN"), *node.to_tokens(), _tok(")", "PAREN")]


def absolute_if_negative(node: ExprNode) -> ExprNode | None:
    """If ``node`` renders with a leading minus that can be factored out, return
    the positive version; otherwise return ``None``.

    Used to print ``x + (-3)`` as ``x - 3``.
    """
    if isinstance(node, ConstantNode) and node.value < 0:
        return ConstantNode(-node.value)
    if isinstance(node, VariableNode) and node.coefficient < 0:
        return VariableNode(node.name, -node.coefficient)
    if isinstance(node, GroupNode) and node.multiplier < 0:
        return GroupNode(node.inner, -node.multiplier)
    if isinstance(node, BinaryOpNode) and node.op in ("*", "/"):
        left_magnitude = absolute_if_negative(node.left)
        if left_magnitude is not None:
            return BinaryOpNode(node.op, left_magnitude, node.right)
    return None


# ---------------------------------------------------------------------------
# Structural helpers shared by the equation engine
# ---------------------------------------------------------------------------


def negate(node: ExprNode) -> ExprNode:
    """Return an expression equal to ``-node``, pushing the sign inward."""
    if isinstance(node, ConstantNode):
        return ConstantNode(-node.value)
    if isinstance(node, VariableNode):
        return VariableNode(node.name, -node.coefficient)
    if isinstance(node, GroupNode):
        return GroupNode(node.inner, -node.multiplier)
    if isinstance(node, BinaryOpNode):
        if node.op == "+":
            return BinaryOpNode("-", negate(node.left), node.right)
        if node.op == "-":
            return BinaryOpNode("+", negate(node.left), node.right)
        return BinaryOpNode(node.op, negate(node.left), node.right)
    raise TypeError(f"cannot negate {type(node).__name__}")


def flatten_sum(node: ExprNode) -> list[ExprNode]:
    """Flatten a chain of ``+``/``-`` into signed top-level terms.

    ``3x + 4 - 2x`` -> ``[3x, 4, -2x]``. Groups and products are atomic terms.
    """
    if isinstance(node, BinaryOpNode):
        if node.op == "+":
            return flatten_sum(node.left) + flatten_sum(node.right)
        if node.op == "-":
            return flatten_sum(node.left) + [negate(term) for term in flatten_sum(node.right)]
    return [node]


def build_sum(terms: Sequence[ExprNode]) -> ExprNode:
    """Inverse of :func:`flatten_sum`: build a left-associative sum.

    Negative terms are emitted as subtraction (``x - 3`` rather than ``x + -3``).
    An empty sequence yields the constant ``0``.
    """
    if not terms:
        return ConstantNode(Fraction(0))
    accumulator = terms[0]
    for term in terms[1:]:
        magnitude = absolute_if_negative(term)
        if magnitude is not None:
            accumulator = BinaryOpNode("-", accumulator, magnitude)
        else:
            accumulator = BinaryOpNode("+", accumulator, term)
    return accumulator


# ---------------------------------------------------------------------------
# Convenience constructors (keep call sites short and type-checker friendly)
# ---------------------------------------------------------------------------


def const(value: Number) -> ConstantNode:
    return ConstantNode(to_fraction(value))


def var(coefficient: Number = 1, name: str = "x") -> VariableNode:
    return VariableNode(name, to_fraction(coefficient))


def group(inner: ExprNode, multiplier: Number = 1) -> GroupNode:
    return GroupNode(inner, to_fraction(multiplier))


def add(left: ExprNode, right: ExprNode) -> BinaryOpNode:
    return BinaryOpNode("+", left, right)


def sub(left: ExprNode, right: ExprNode) -> BinaryOpNode:
    return BinaryOpNode("-", left, right)


def mul(left: ExprNode, right: ExprNode) -> BinaryOpNode:
    return BinaryOpNode("*", left, right)


def div(left: ExprNode, right: ExprNode) -> BinaryOpNode:
    return BinaryOpNode("/", left, right)
