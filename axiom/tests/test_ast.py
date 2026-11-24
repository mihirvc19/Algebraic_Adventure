from fractions import Fraction

import pytest

from core.ast_nodes import (
    BinaryOpNode,
    ConstantNode,
    ExprNode,
    GroupNode,
    VariableNode,
    add,
    build_sum,
    const,
    div,
    flatten_sum,
    group,
    mul,
    negate,
    sub,
    var,
)

# ---------------------------------------------------------------- evaluation


def test_constant_and_variable_evaluate() -> None:
    assert const(7).evaluate(Fraction(100)) == 7
    assert var(3).evaluate(Fraction(4)) == 12
    assert var(Fraction(1, 2)).evaluate(Fraction(3)) == Fraction(3, 2)


def test_binary_and_group_evaluate() -> None:
    expr = add(group(add(var(), const(3)), 2), const(4))  # 2(x + 3) + 4
    assert expr.evaluate(Fraction(5)) == 20
    assert sub(var(5), const(2)).evaluate(Fraction(1)) == 3
    assert mul(const(3), var()).evaluate(Fraction(2)) == 6
    assert div(var(), const(3)).evaluate(Fraction(4)) == Fraction(4, 3)


def test_division_by_zero_raises() -> None:
    with pytest.raises(ZeroDivisionError):
        div(const(1), sub(var(), const(2))).evaluate(Fraction(2))


def test_fractions_stay_exact() -> None:
    expr = div(const(4), const(3))
    assert expr.evaluate(Fraction(0)) == Fraction(4, 3)
    assert ConstantNode(Fraction(4, 3)).to_string() == "4/3"


def test_constructors_coerce_ints_to_fractions() -> None:
    node = ConstantNode(3)  # type: ignore[arg-type]
    assert isinstance(node.value, Fraction)
    assert VariableNode("x", 2).coefficient == Fraction(2)  # type: ignore[arg-type]


def test_invalid_operator_rejected() -> None:
    with pytest.raises(ValueError):
        BinaryOpNode("^", const(1), const(2))  # type: ignore[arg-type]


# ------------------------------------------------------------------- cloning


def test_clone_is_deep_and_structurally_equal() -> None:
    expr = add(group(sub(var(2), const(3)), 4), div(var(), const(5)))
    copy = expr.clone()
    assert copy == expr
    assert copy is not expr
    assert isinstance(copy, BinaryOpNode)
    assert copy.left is not expr.left
    assert copy.evaluate(Fraction(7)) == expr.evaluate(Fraction(7))


def test_nodes_are_immutable() -> None:
    node = const(3)
    with pytest.raises(AttributeError):
        node.value = Fraction(4)  # type: ignore[misc]


# ---------------------------------------------------------------- formatting


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        (var(), "x"),
        (var(3), "3x"),
        (var(-1), "-x"),
        (var(-4), "-4x"),
        (var(Fraction(1, 3)), "x/3"),
        (var(Fraction(-2, 3)), "-2x/3"),
        (const(-5), "-5"),
        (add(var(3), const(4)), "3x + 4"),
        (add(var(3), const(-4)), "3x - 4"),
        (sub(var(3), const(-4)), "3x + 4"),
        (add(var(5), var(-2)), "5x - 2x"),
        (group(add(var(), const(3)), 2), "2(x + 3)"),
        (group(sub(var(), const(3)), -1), "-(x - 3)"),
        (group(add(var(2), const(6)), Fraction(1, 2)), "(2x + 6)/2"),
        (add(group(add(var(), const(3)), 2), const(4)), "2(x + 3) + 4"),
        (sub(const(10), add(var(), const(1))), "10 - (x + 1)"),
        (mul(const(3), add(var(), const(2))), "3(x + 2)"),
        (mul(var(), const(-2)), "x * (-2)"),
        (div(add(var(), const(1)), const(2)), "(x + 1) / 2"),
        (add(var(), group(add(var(), const(1)), -2)), "x - 2(x + 1)"),
    ],
)
def test_to_string(expr: ExprNode, expected: str) -> None:
    assert expr.to_string() == expected
    assert str(expr) == expected


def test_tokens_join_to_string_and_are_tagged() -> None:
    expr = add(group(add(var(3), const(4)), 2), const(-1))
    tokens = expr.to_tokens()
    assert "".join(t["text"] for t in tokens) == expr.to_string() == "2(3x + 4) - 1"
    by_text = [(t["text"], t["type"]) for t in tokens]
    assert ("2", "COEFFICIENT") in by_text
    assert ("3", "COEFFICIENT") in by_text
    assert ("x", "VARIABLE") in by_text
    assert ("4", "CONSTANT") in by_text
    assert ("1", "CONSTANT") in by_text
    assert ("(", "PAREN") in by_text
    assert (" - ", "OPERATOR") in by_text


# --------------------------------------------------------- structural helpers


def test_negate_preserves_value() -> None:
    exprs: list[ExprNode] = [
        const(3),
        var(-2),
        group(add(var(), const(1)), 3),
        add(var(2), const(5)),
        sub(var(2), const(5)),
        mul(const(2), var()),
        div(var(), const(4)),
    ]
    for expr in exprs:
        for x in (Fraction(-3), Fraction(0), Fraction(7, 2)):
            assert negate(expr).evaluate(x) == -expr.evaluate(x)


def test_flatten_and_build_sum_round_trip() -> None:
    expr = sub(add(var(3), const(4)), sub(var(2), const(1)))  # 3x + 4 - (2x - 1)
    terms = flatten_sum(expr)
    assert terms == [var(3), const(4), var(-2), const(1)]
    rebuilt = build_sum(terms)
    assert rebuilt.to_string() == "3x + 4 - 2x + 1"
    for x in range(-5, 6):
        assert rebuilt.evaluate(Fraction(x)) == expr.evaluate(Fraction(x))


def test_build_sum_empty_is_zero() -> None:
    assert build_sum([]) == const(0)


def test_group_node_default_multiplier() -> None:
    node = GroupNode(add(var(), const(1)))
    assert node.multiplier == 1
    assert node.to_string() == "(x + 1)"
