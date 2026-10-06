import ast
import operator
import re
from dataclasses import dataclass

from circlesearch.core.cards import TextCard
from circlesearch.core.pipeline import resolver
from circlesearch.core.routing import recognizer
from circlesearch.core.text import fmt, parse_number

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}
MATH_CHARS = re.compile(r"^[\d\s.,+\-*/×÷^()%]+$")


@dataclass(kw_only=True)
class MathCard(TextCard):
    kind = "math"
    title_role = "query"


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        return -_eval(node.operand) if isinstance(node.op, ast.USub) else _eval(node.operand)
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 100:
            raise ValueError("exponent too large")
        return OPS[type(node.op)](left, right)
    raise ValueError("not arithmetic")


@recognizer("math", order=100)
def parse_math(text):
    t = text.strip().rstrip("=").strip()
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s?%\s+of\s+(\d[\d,]*(?:\.\d+)?)", t, re.I)
    if m:
        return float(m.group(1).replace(",", ".")) / 100 * parse_number(m.group(2))
    if not MATH_CHARS.match(t) or not re.search(r"\d\s*[-+*/×÷^%]\s*[\d(]", t) or len(re.findall(r"\d+", t)) < 2:
        return None
    if re.fullmatch(r"[\d\s()+-]{9,}", t) or re.fullmatch(r"\d{1,4}([./-])\d{1,2}\1\d{1,4}", t):
        return None
    expr = t.replace("×", "*").replace("÷", "/").replace("^", "**").replace(",", "")
    expr = re.sub(r"(\d+(?:\.\d+)?)\s?%", r"(\1/100)", expr)
    try:
        return float(_eval(ast.parse(expr, mode="eval")))
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError, TypeError):
        return None


@resolver("math")
def math_card(route):
    result = route.value
    shown = fmt(result, 6) if abs(result) < 1e15 else f"{result:.6g}"
    return MathCard(title=route.text, value=shown)
