"""A tiny, safe expression evaluator for decision points and validation rules.

We deliberately avoid ``eval``. Only a small, auditable grammar is supported:
names (resolved from a flat context), literals, boolean ops, ``not``,
comparisons, membership, and basic arithmetic. Unknown names resolve to ``None``
so authors can write tolerant rules.
"""

from __future__ import annotations

import ast
import operator
from typing import Any, Dict

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
}

_CMP_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}


class ExprError(ValueError):
    """Raised when an expression uses unsupported syntax."""


def _eval(node: ast.AST, ctx: Dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, ctx)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return ctx.get(node.id)
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, ctx) for v in node.values]
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in values:
                result = result and v
            return result
        result = False
        for v in values:
            result = result or v
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval(node.operand, ctx)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval(node.operand, ctx)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        return _BIN_OPS[type(node.op)](_eval(node.left, ctx), _eval(node.right, ctx))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, ctx)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, ctx)
            if isinstance(op, ast.In):
                ok = left in right if right is not None else False
            elif isinstance(op, ast.NotIn):
                ok = left not in right if right is not None else True
            elif type(op) in _CMP_OPS:
                if left is None or right is None:
                    ok = _CMP_OPS[type(op)](left, right) if (
                        isinstance(op, (ast.Eq, ast.NotEq))
                    ) else False
                else:
                    ok = _CMP_OPS[type(op)](left, right)
            else:
                raise ExprError(f"unsupported comparator: {ast.dump(op)}")
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_eval(e, ctx) for e in node.elts]
    raise ExprError(f"unsupported expression node: {type(node).__name__}")


def safe_eval(expression: str, context: Dict[str, Any]) -> Any:
    """Evaluate ``expression`` against ``context``. Empty expr -> ``True``."""
    expr = (expression or "").strip()
    if not expr:
        return True
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:  # pragma: no cover - defensive
        raise ExprError(f"invalid expression: {expr!r}") from exc
    return _eval(tree, context)
