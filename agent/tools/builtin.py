"""内置安全工具模块（本节先实现 AST 安全计算器）。""" 
from __future__ import annotations 

import ast
import math
import operator
from typing import Any,Callable

_BIN_OPS:dict[type,Callable[[Any,Any],Any]] = {
    ast.Add:operator.add,ast.Sub:operator.sub,
    ast.Mult:operator.mul,ast.Div:operator.truediv,
    ast.FloorDiv:operator.floordiv,ast.Mod:operator.mod,
    ast.Pow:operator.pow
} 
_UNARY_OPS: dict[type, Callable[[Any], Any]] = {
    ast.USub: operator.neg, ast.UAdd: operator.pos
}
_FUNCS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max,
    "log": math.log, "log10": math.log10, "sin": math.sin, "cos": math.cos, "tan": math.tan,
}
_CONSTS: dict[str, float] = {"pi": math.pi, "e": math.e}
MAX_EXPRESSION_LEN, MAX_EXPONENT, MAX_ABS_RESULT = 200, 1000, 10 ** 100

def _eval_node(node: ast.AST) -> int | float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _eval_node(node.left), _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise ValueError(f"指数超过 {MAX_EXPONENT}，拒绝计算以防止算力耗尽")
        result = _BIN_OPS[type(node.op)](left, right)
        if isinstance(result, (int, float)) and abs(result) > MAX_ABS_RESULT:
            raise ValueError("结果数值过大")
        return result
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCS
        and not node.keywords
    ):
        return _FUNCS[node.func.id](*(_eval_node(arg) for arg in node.args))
    raise ValueError(f"不支持的语法: {type(node).__name__}")

def safe_eval(expression: str) -> int | float:
    expression = expression.strip()
    if not expression:
        raise ValueError("表达式为空")
    if len(expression) > MAX_EXPRESSION_LEN:
        raise ValueError(f"表达式过长（上限 {MAX_EXPRESSION_LEN} 字符）")
    expression = expression.replace("×", "*").replace("÷", "/").replace("^", "**")
    tree = ast.parse(expression, mode="eval")
    return _eval_node(tree.body)

def _format_number(value: int | float) -> str:
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))           # 如 21.0 -> "21"，同时避免超大浮点强转失真
        return f"{value:.10g}"               # 如 0.1+0.2 -> "0.3"，消去 IEEE754 尾数误差
    return str(value)


def calculator(expression: str) -> str:
    """安全计算数学表达式，异常时返回可读错误提示以引导模型自愈重试。"""
    try:
        return _format_number(safe_eval(expression))
    except ZeroDivisionError:
        return "计算错误：除数不能为 0"
    except (ValueError, SyntaxError, TypeError, OverflowError) as exc:
        return f"计算错误：{exc}。请修正表达式后重试。"