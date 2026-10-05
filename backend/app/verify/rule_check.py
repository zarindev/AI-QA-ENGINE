"""Detection layer 3: business-rule recalculation in Python.

For a test linked to a confirmed rule, Claude does not judge the rule. It only *reads values* off the final page
and writes the rule's condition as an arithmetic/boolean expression over those named values. Python then
evaluates the expression with a tiny whitelisted evaluator, giving an independent verdict on the agent's.
"""

from __future__ import annotations

import ast
import base64
import operator
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from app.execute import media

_BIN = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CMP = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
}
_FUNCS: dict[str, Callable[..., Any]] = {"round": round, "min": min, "max": max, "abs": abs}
_TOLERANCE = 0.005  # money values shown with 2 decimals


class UnsafeExpression(ValueError):
    pass


def safe_eval(expression: str, variables: dict[str, float]) -> Any:
    """Evaluate arithmetic / comparison / boolean expressions over numbers. Anything else is refused."""
    tree = ast.parse(expression, mode="eval")

    def ev(node: ast.AST) -> Any:
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float | bool):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise UnsafeExpression(f"unknown value '{node.id}'")
            return variables[node.id]
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
            if isinstance(node.op, ast.Pow):
                raise UnsafeExpression("powers are not allowed")
            return _BIN[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd | ast.Not):
            v = ev(node.operand)
            return -v if isinstance(node.op, ast.USub) else (+v if isinstance(node.op, ast.UAdd) else not v)
        if isinstance(node, ast.BoolOp):
            values = [ev(v) for v in node.values]
            return all(values) if isinstance(node.op, ast.And) else any(values)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comp in zip(node.ops, node.comparators, strict=True):
                if type(op) not in _CMP:
                    raise UnsafeExpression("comparison not allowed")
                right = ev(comp)
                if (
                    isinstance(op, ast.Eq | ast.NotEq)
                    and isinstance(left, float | int)
                    and isinstance(right, float | int)
                ):
                    equal = abs(left - right) <= _TOLERANCE
                    if equal != isinstance(op, ast.Eq):
                        return False
                elif not _CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.IfExp):
            return ev(node.body) if ev(node.test) else ev(node.orelse)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS
            and not node.keywords
        ):
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise UnsafeExpression(f"'{ast.dump(node)[:60]}' is not allowed")

    return ev(tree)


class Value(BaseModel):
    name: str
    value: float
    seen_as: str


class Extraction(BaseModel):
    applicable: bool
    values: list[Value]
    expression: str
    explanation: str


class RuleCheck(BaseModel):
    rule_id: str
    expression: str
    values: dict[str, float]
    holds: bool | None
    explanation: str
    error: str = ""


SYSTEM = (
    "You support an automated test. Do NOT judge whether the application is right. Your only jobs: (1) read the "
    "numeric values on the final page that the business rule talks about (amounts, percentages, counts, days); "
    "(2) write the rule's condition as a Python expression over those values, using only numbers, + - * / //, "
    "comparisons, and/or/not, round(), min(), max(), abs(). Variable names: snake_case, one per value. Example: "
    "values fee=120, coverage_pct=50, patient_pays=120 → expression 'patient_pays == round(fee * (1 - coverage_pct / 100), 2)'. "
    "If the page does not show the values the rule needs, set applicable=false."
)


def check_rule(
    ai: Any, rule_id: str, statement: str, condition: str, page_text: str, png: bytes | None
) -> RuleCheck:
    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": f"# Rule {rule_id}\n{statement}\nCondition: {condition}\n\n# Final page text\n{page_text[:4000]}",
        },
    ]
    if png:
        content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.standard_b64encode(media.model_image(png)).decode("ascii"),
                },
            }
        )
    ex: Extraction = ai.structured(
        system=SYSTEM,
        content=content,
        schema=Extraction,
        purpose="read rule values",
        effort="low",
        max_tokens=4000,
        use_cache=False,
    )
    values = {v.name: v.value for v in ex.values}
    if not ex.applicable:
        return RuleCheck(
            rule_id=rule_id,
            expression=ex.expression,
            values=values,
            holds=None,
            explanation=ex.explanation,
            error="The final page does not show the values this rule needs.",
        )
    try:
        holds = bool(safe_eval(ex.expression, values))
    except (UnsafeExpression, SyntaxError, ZeroDivisionError, TypeError) as exc:
        return RuleCheck(
            rule_id=rule_id,
            expression=ex.expression,
            values=values,
            holds=None,
            explanation=ex.explanation,
            error=str(exc),
        )
    return RuleCheck(
        rule_id=rule_id, expression=ex.expression, values=values, holds=holds, explanation=ex.explanation
    )
