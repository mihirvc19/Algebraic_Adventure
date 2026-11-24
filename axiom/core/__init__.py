"""Axiom core: pure-Python, UI-free algebra combat engine.

Nothing in this package imports a UI or game library. A presentation layer
drives :class:`CombatEngine` and reacts to the :mod:`core.events` it returns.
"""

from .ast_nodes import BinaryOpNode, ConstantNode, ExprNode, GroupNode, Token, VariableNode
from .cards import (
    AddConstantCard,
    AddVariableCard,
    CombineLikeTermsCard,
    DistributeCard,
    DivideCard,
    ExecuteSolveCard,
    IllegalCardPlayError,
    MultiplyCard,
    OperationCard,
    SubtractConstantCard,
    SubtractVariableCard,
)
from .combat import (
    CardInstance,
    CombatConfig,
    CombatEngine,
    CombatState,
    EnemyState,
    IllegalActionError,
    Intent,
    PlayerState,
    TurnPhase,
)
from .equation import Equation
from .generator import generate_equation
from .solver import next_step, plan_solution

__all__ = [
    "AddConstantCard",
    "AddVariableCard",
    "BinaryOpNode",
    "CardInstance",
    "CombatConfig",
    "CombatEngine",
    "CombatState",
    "CombineLikeTermsCard",
    "ConstantNode",
    "DistributeCard",
    "DivideCard",
    "EnemyState",
    "Equation",
    "ExecuteSolveCard",
    "ExprNode",
    "GroupNode",
    "IllegalActionError",
    "IllegalCardPlayError",
    "Intent",
    "MultiplyCard",
    "OperationCard",
    "PlayerState",
    "SubtractConstantCard",
    "SubtractVariableCard",
    "Token",
    "TurnPhase",
    "VariableNode",
    "generate_equation",
    "next_step",
    "plan_solution",
]
