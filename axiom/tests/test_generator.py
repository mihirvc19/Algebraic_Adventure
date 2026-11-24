import re
from fractions import Fraction

import pytest

from core.ast_nodes import GroupNode, flatten_sum
from core.cards import ExecuteSolveCard
from core.equation import Equation
from core.generator import generate_equation
from core.solver import plan_solution


def _solve_with_plan(eq: Equation) -> Fraction | None:
    steps = plan_solution(eq)
    assert steps and isinstance(steps[-1], ExecuteSolveCard), f"solver stuck on {eq}: {steps}"
    for card in steps[:-1]:
        assert card.can_play(eq), f"{card.name} unplayable on {eq}"
        eq = card.preview(eq)
    return eq.get_solution()


def test_same_seed_is_deterministic() -> None:
    for tier in (1, 2, 3):
        assert generate_equation(tier, seed=42) == generate_equation(tier, seed=42)


def test_invalid_tier_rejected() -> None:
    for tier in (0, 4, -1):
        with pytest.raises(ValueError):
            generate_equation(tier, seed=1)


def test_tier1_is_one_step() -> None:
    for seed in range(200):
        eq, root = generate_equation(1, seed)
        assert -9 <= root <= 9
        steps = plan_solution(eq)
        assert len(steps) == 2, f"{eq} should be one step + execute, got {steps}"


def test_tier2_is_two_step_with_nonzero_root() -> None:
    for seed in range(200):
        eq, root = generate_equation(2, seed)
        assert root != 0 and -9 <= root <= 9
        lhs_terms = flatten_sum(eq.lhs)
        assert len(lhs_terms) == 2
        assert len(plan_solution(eq)) == 3


def test_tier3_has_parentheses_or_variables_on_both_sides() -> None:
    shapes = set()
    for seed in range(200):
        eq, root = generate_equation(3, seed)
        assert root != 0
        has_group = any(isinstance(t, GroupNode) for t in flatten_sum(eq.lhs))
        both_sides = eq.lhs.contains_variable() and eq.rhs.contains_variable()
        assert has_group or both_sides, str(eq)
        shapes.add("group" if has_group else "both")
    assert shapes == {"group", "both"}


def test_example_shapes_render_cleanly() -> None:
    rendered = {generate_equation(tier, seed)[0].to_string() for tier in (1, 2, 3) for seed in range(50)}
    for s in rendered:
        assert "+ -" not in s and "- -" not in s, s
        assert not re.search(r"(?<![0-9])1x", s), s


def test_fuzz_1000_equations_all_tiers() -> None:
    for i in range(1000):
        tier = i % 3 + 1
        eq, root = generate_equation(tier, seed=i)
        assert eq.lhs.evaluate(Fraction(root)) == eq.rhs.evaluate(Fraction(root))
        assert eq.solve_exact() == root
        if tier >= 2:
            assert root != 0
        # The solver must reach the exact root without division-by-zero errors.
        assert _solve_with_plan(eq) == root


def test_unseeded_generation_works() -> None:
    eq, root = generate_equation(2)
    assert eq.satisfied_by(root)
