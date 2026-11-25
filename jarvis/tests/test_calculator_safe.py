"""Regression tests for the safe calculator (no eval surface).

These tests exercise the pure math evaluator extracted from the calculator
path so they can run without the full desktop / voice / AI dependency tree.
"""
import ast
import operator
import pytest

# Mirror of the implementation in jarvis/app/main.py so the test stays
# independent of optional imports. Keep in sync when the production function changes.
_SAFE_MATH_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

def _safe_eval_math(expr: str):
    """Evaluate a pure arithmetic expression with no builtins or names."""
    tree = ast.parse(expr.strip(), mode="eval")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError("only numeric constants allowed")
        if isinstance(node, ast.Num):  # type: ignore[attr-defined]
            return node.n
        if isinstance(node, ast.BinOp):
            op = _SAFE_MATH_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"operator {type(node.op).__name__} not allowed")
            return op(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            op = _SAFE_MATH_OPS.get(type(node.op))
            if op is None:
                raise ValueError(f"unary {type(node.op).__name__} not allowed")
            return op(_eval(node.operand))
        raise ValueError(f"unsupported expression node: {type(node).__name__}")

    return _eval(tree)


def test_basic_arithmetic():
    assert _safe_eval_math("2 + 3") == 5
    assert _safe_eval_math("10 - 4") == 6
    assert _safe_eval_math("3 * 4") == 12
    assert _safe_eval_math("10 / 2") == 5.0
    assert _safe_eval_math("10 // 3") == 3
    assert _safe_eval_math("10 % 3") == 1
    assert _safe_eval_math("2 ** 3") == 8


def test_precedence_and_parens():
    assert _safe_eval_math("2 + 3 * 4") == 14
    assert _safe_eval_math("(2 + 3) * 4") == 20
    assert _safe_eval_math("2 ** 3 ** 2") == 512  # right-assoc
    assert _safe_eval_math("(10 - 2) / 4") == 2.0


def test_unary():
    assert _safe_eval_math("-5") == -5
    assert _safe_eval_math("+3") == 3
    assert _safe_eval_math("-(2 + 3)") == -5


def test_rejects_names_and_calls():
    with pytest.raises(ValueError):
        _safe_eval_math("__import__('os')")
    with pytest.raises(ValueError):
        _safe_eval_math("abs(-1)")


def test_rejects_non_numeric_constants():
    with pytest.raises(ValueError):
        _safe_eval_math("'hello'")


def test_whitespace_and_floats():
    assert _safe_eval_math("  1.5 + 2.5  ") == 4.0
    assert abs(_safe_eval_math("0.1 + 0.2") - 0.3) < 1e-9
