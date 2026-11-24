from fractions import Fraction

import pytest

from core.ast_nodes import add, build_sum, const, group, mul, sub, var
from core.equation import Cancellation, Equation


def eq_2x3_plus_4() -> Equation:
    """2(x + 3) + 4 = 20"""
    return Equation(add(group(add(var(), const(3)), 2), const(4)), const(20))


def test_equation_string_and_tokens() -> None:
    eq = eq_2x3_plus_4()
    assert eq.to_string() == "2(x + 3) + 4 = 20"
    assert "".join(t["text"] for t in eq.to_tokens()) == eq.to_string()
    assert eq.satisfied_by(5)
    assert not eq.satisfied_by(4)
    assert eq.solve_exact() == 5


def test_manual_solve_sequence_from_plan() -> None:
    eq = eq_2x3_plus_4()
    eq = eq.apply_binary_both_sides("-", const(4))
    assert eq.to_string() == "2(x + 3) = 16"
    eq = eq.apply_binary_both_sides("/", const(2))
    assert eq.to_string() == "x + 3 = 8"
    eq = eq.apply_binary_both_sides("-", const(3))
    assert eq.to_string() == "x = 5"
    assert eq.is_solved()
    assert eq.get_solution() == 5


def test_alternative_solve_via_distribute_and_combine() -> None:
    eq = eq_2x3_plus_4().distribute()
    assert eq.to_string() == "2x + 6 + 4 = 20"
    eq = eq.combine_like_terms()
    assert eq.to_string() == "2x + 10 = 20"
    eq = eq.apply_binary_both_sides("-", const(10)).apply_binary_both_sides("/", const(2))
    assert eq.to_string() == "x = 5"


def test_trivial_identities_are_reported() -> None:
    result = Equation(add(var(3), const(4)), const(19)).transform_binary_both_sides("-", const(4))
    assert result.equation.to_string() == "3x = 15"
    assert result.cancellations == (Cancellation("lhs", "4"),)

    result = result.equation.transform_binary_both_sides("/", const(3))
    assert result.equation.to_string() == "x = 5"
    assert result.cancellations == (Cancellation("lhs", "3"),)


def test_non_cancelling_addition_stays_granular() -> None:
    eq = Equation(add(var(3), const(4)), const(19)).apply_binary_both_sides("-", const(2))
    assert eq.to_string() == "3x + 4 - 2 = 17"
    assert not eq.is_solved()
    assert eq.combine_like_terms().to_string() == "3x + 2 = 17"


def test_variables_on_both_sides() -> None:
    eq = Equation(add(var(5), const(2)), add(var(2), const(11)))
    eq = eq.apply_binary_both_sides("-", var(2))
    assert eq.to_string() == "5x + 2 - 2x = 11"
    eq = eq.combine_like_terms()
    assert eq.to_string() == "3x + 2 = 11"


def test_multiplying_a_sum_wraps_it_in_a_group() -> None:
    eq = Equation(add(var(2), const(6)), const(10))
    halved = eq.apply_binary_both_sides("/", const(2))
    assert halved.to_string() == "(2x + 6)/2 = 5"
    assert halved.distribute().to_string() == "x + 3 = 5"
    doubled = Equation(group(add(var(), const(1)), 2), const(8)).apply_binary_both_sides("*", const(3))
    assert doubled.to_string() == "6(x + 1) = 24"


def test_fraction_coefficients_are_exact() -> None:
    eq = Equation(var(3), const(4)).apply_binary_both_sides("/", const(3))
    assert eq.to_string() == "x = 4/3"
    assert eq.get_solution() == Fraction(4, 3)


def test_multiply_or_divide_by_zero_rejected() -> None:
    eq = Equation(var(2), const(4))
    with pytest.raises(ValueError):
        eq.apply_binary_both_sides("/", const(0))
    with pytest.raises(ValueError):
        eq.apply_binary_both_sides("*", const(0))
    with pytest.raises(ValueError):
        eq.apply_binary_both_sides("*", var(2))


def test_combine_like_terms_details() -> None:
    lhs = build_sum([var(2), const(3), var(4), const(-3), group(add(const(1), const(2)), 2)])
    eq = Equation(lhs, add(const(1), const(1)))
    assert eq.combine_like_terms().to_string() == "6x + 6 = 2"
    # Terms that cancel completely disappear.
    assert Equation(add(var(2), var(-2)), const(0)).combine_like_terms().to_string() == "0 = 0"


def test_distribute_nested_and_negative_groups() -> None:
    expr = group(add(group(add(var(), const(1)), 2), const(3)), -1)  # -(2(x + 1) + 3)
    eq = Equation(expr, const(0)).distribute()
    assert eq.to_string() == "-2x - 2 - 3 = 0"
    assert Equation(mul(const(3), sub(var(), const(2))), const(0)).distribute().to_string() == "3x - 6 = 0"


def test_transformations_preserve_solution() -> None:
    eq = Equation(sub(group(add(var(), const(3)), 2), const(4)), add(var(), const(1)))
    root = eq.solve_exact()
    assert root is not None
    for transformed in (
        eq.distribute(),
        eq.combine_like_terms(),
        eq.apply_binary_both_sides("+", const(7)),
        eq.apply_binary_both_sides("*", const(3)),
        eq.apply_binary_both_sides("/", const(5)),
        eq.apply_binary_both_sides("-", var(1)),
    ):
        assert transformed.satisfied_by(root)


def test_is_solved_requires_unit_coefficient_and_single_constant() -> None:
    assert Equation(var(), const(3)).is_solved()
    assert Equation(const(3), var()).is_solved()
    assert Equation(const(3), var()).get_solution() == 3
    assert not Equation(var(2), const(6)).is_solved()
    assert not Equation(var(), add(const(1), const(2))).is_solved()
    assert Equation(var(2), const(6)).get_solution() is None


def test_equation_is_immutable_value_object() -> None:
    eq = eq_2x3_plus_4()
    eq.apply_binary_both_sides("-", const(4))
    assert eq == eq_2x3_plus_4()
    assert eq.clone() == eq
