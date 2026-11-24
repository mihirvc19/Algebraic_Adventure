"""Reverse equation generator.

Equations are never generated forward from random coefficients. Every
equation is built backward from a clean integer root, so the answer is
always a whole number and the generator can check it before returning.
"""

from __future__ import annotations

import random
from fractions import Fraction

from .ast_nodes import ConstantNode, ExprNode, GroupNode, VariableNode, build_sum
from .equation import Equation

MIN_TIER = 1
MAX_TIER = 3
_ROOT_RANGE = (-9, 9)


def generate_equation(tier: int, seed: int | None = None) -> tuple[Equation, int]:
    """Generate an equation of the given difficulty tier together with its root.

    * Tier 1: one-step linear (``x + 7 = 11``, ``x - 3 = 2``, ``3x = 15``).
    * Tier 2: two-step linear (``3x + 4 = 19``).
    * Tier 3: parentheses (``2(x + 3) = 14``, ``2(x - 1) + 5 = 13``) or
      variables on both sides (``5x + 2 = 2x + 11``).

    The same ``seed`` always yields the same equation.
    """
    return generate_equation_with_rng(tier, random.Random(seed))


def generate_equation_with_rng(tier: int, rng: random.Random) -> tuple[Equation, int]:
    if not MIN_TIER <= tier <= MAX_TIER:
        raise ValueError(f"tier must be between {MIN_TIER} and {MAX_TIER}, got {tier}")

    target = _pick_root(rng, allow_zero=(tier == 1))
    if tier == 1:
        equation = _one_step(target, rng)
    elif tier == 2:
        equation = _two_step(target, rng)
    else:
        equation = _parentheses(target, rng) if rng.random() < 0.5 else _both_sides(target, rng)

    _verify(equation, target)
    return equation, target


def _pick_root(rng: random.Random, *, allow_zero: bool) -> int:
    low, high = _ROOT_RANGE
    candidates = [value for value in range(low, high + 1) if allow_zero or value != 0]
    return rng.choice(candidates)


def _signed(rng: random.Random, low: int, high: int) -> int:
    magnitude = rng.randint(low, high)
    return magnitude if rng.random() < 0.5 else -magnitude


def _constant_side(value: int) -> ConstantNode:
    return ConstantNode(Fraction(value))


def _linear(coefficient: int, constant: int) -> ExprNode:
    """Build ``coefficient*x + constant``, omitting a zero constant."""
    terms: list[ExprNode] = [VariableNode("x", Fraction(coefficient))]
    if constant != 0:
        terms.append(ConstantNode(Fraction(constant)))
    return build_sum(terms)


def _one_step(target: int, rng: random.Random) -> Equation:
    kind = rng.choice(("add", "subtract", "multiply"))
    if kind == "multiply":
        k = rng.randint(2, 5)
        return Equation(VariableNode("x", Fraction(k)), _constant_side(k * target))
    c = rng.randint(1, 12)
    offset = c if kind == "add" else -c
    return Equation(_linear(1, offset), _constant_side(target + offset))


def _two_step(target: int, rng: random.Random) -> Equation:
    a = rng.randint(2, 5)
    b = _signed(rng, 1, 12)
    return Equation(_linear(a, b), _constant_side(a * target + b))


def _parentheses(target: int, rng: random.Random) -> Equation:
    multiplier = rng.randint(2, 5)
    c = _signed(rng, 1, 9)
    lhs: ExprNode = GroupNode(_linear(1, c), Fraction(multiplier))
    rhs_value = multiplier * (target + c)
    if rng.random() < 0.5:
        d = _signed(rng, 1, 12)
        lhs = build_sum([lhs, ConstantNode(Fraction(d))])
        rhs_value += d
    return Equation(lhs, _constant_side(rhs_value))


def _both_sides(target: int, rng: random.Random) -> Equation:
    a = rng.randint(2, 5)
    b = _signed(rng, 1, 12)
    k = rng.randint(1, 5)
    # Start from a*x + b = a*t + b, then add k*x to both sides.
    return Equation(_linear(a + k, b), _linear(k, a * target + b))


def _verify(equation: Equation, target: int) -> None:
    root = Fraction(target)
    if equation.lhs.evaluate(root) != equation.rhs.evaluate(root):
        raise RuntimeError(f"generator produced {equation} which is not satisfied by x = {target}")
    if not equation.has_unique_solution():
        raise RuntimeError(f"generator produced {equation} without a unique solution")
