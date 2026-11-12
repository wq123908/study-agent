"""内置工具：时间、AST 安全计算器、长期记忆读写、沙箱文件写入（高危演示）。"""
from __future__ import annotations

import ast
import math
import operator
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Callable

from pydantic import Field

from agent.tools.base import RiskLevel, ToolContext, ToolRegistry

# ======================================================================
# 安全 AST 计算器（彻底替代 eval）
# ======================================================================
_BIN_OPS: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS: dict[type, Callable[[Any], Any]] = {ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS: dict[str, Callable[..., Any]] = {
    "sqrt": math.sqrt, "abs": abs, "round": round, "min": min, "max": max,
    "log": math.log, "log10": math.log10, "sin": math.sin, "cos": math.cos, "tan": math.tan,
}
_CONSTS: dict[str, float] = {"pi": math.pi, "e": math.e}

MAX_EXPRESSION_LEN = 200
MAX_EXPONENT = 1000
MAX_ABS_RESULT = 10 ** 100


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
            return str(int(value))
        return f"{value:.10g}"
    return str(value)


# ======================================================================
# 工具注册
# ======================================================================
_SAFE_FILENAME = re.compile(r"^[\w\-.\u4e00-\u9fff]{1,80}$")


def register_builtin_tools(registry: ToolRegistry) -> ToolRegistry:
    @registry.tool(risk_level=RiskLevel.READ_ONLY, timeout=2)
    def get_current_time() -> str:
        """获取当前的本地日期、时间和星期。用户问时间、日期、今天几号、星期几时使用。"""
        now = datetime.now().astimezone()
        weekday = "一二三四五六日"[now.weekday()]
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')} 星期{weekday} (UTC{now.strftime('%z')})"

    @registry.tool(risk_level=RiskLevel.READ_ONLY, timeout=2)
    def calculator(
        expression: Annotated[str, Field(description="数学表达式，例如 12*(3+4) 或 sqrt(2)**3")],
    ) -> str:
        """计算数学表达式，支持 + - * / // % ** 括号，以及 sqrt/abs/round/min/max/log/sin/cos/tan 和常量 pi/e。"""
        try:
            return _format_number(safe_eval(expression))
        except ZeroDivisionError:
            return "计算错误：除数不能为 0"
        except (ValueError, SyntaxError, TypeError, OverflowError) as exc:
            return f"计算错误：{exc}。请修正表达式后重试。"

    @registry.tool(risk_level=RiskLevel.WRITE, timeout=5)
    def remember_fact(
        fact: Annotated[str, Field(description="需要长期记住的关于用户的事实或偏好，一句话", max_length=300)],
        ctx: ToolContext,
    ) -> str:
        """把关于用户的长期事实/偏好写入长期记忆（跨会话可用）。仅在用户明确要求记住，或透露稳定的个人偏好时使用。"""
        if ctx.long_term is None:
            return "长期记忆未启用"
        added = ctx.long_term.add(ctx.user_id, fact)
        return "已记住" if added else "该事实已存在，无需重复记忆"

    @registry.tool(risk_level=RiskLevel.READ_ONLY, timeout=5)
    def recall_facts(
        query: Annotated[str, Field(description="检索关键词")],
        ctx: ToolContext,
    ) -> str:
        """从长期记忆中检索与关键词相关的用户事实。"""
        if ctx.long_term is None:
            return "长期记忆未启用"
        hits = ctx.long_term.search(ctx.user_id, query, top_k=5)
        return "\n".join(f"- {h}" for h in hits) if hits else "没有相关记忆"

    @registry.tool(risk_level=RiskLevel.HIGH_RISK, timeout=5)
    def write_workspace_file(
        filename: Annotated[str, Field(description="文件名（不含目录），例如 report.md")],
        content: Annotated[str, Field(description="要写入的完整文本内容", max_length=20000)],
        ctx: ToolContext,
    ) -> str:
        """把文本写入沙箱工作目录中的文件（会覆盖同名文件）。属于高危操作，需要用户审批后才会执行。"""
        if not _SAFE_FILENAME.match(filename) or filename.startswith("."):
            return "文件名非法：只允许字母、数字、中文、下划线、短横线和点，且不能包含目录"
        base = Path(ctx.workspace_dir or "data/workspace").resolve()
        target = (base / filename).resolve()
        if target.parent != base:
            return "拒绝写入：目标路径越出沙箱目录"
        base.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"已写入 {filename}（{len(content)} 字符）"

    return registry
