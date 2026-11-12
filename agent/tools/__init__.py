from agent.tools.base import RiskLevel, ToolContext, ToolRegistry, ToolSpec
from agent.tools.builtin import register_builtin_tools, safe_eval
from agent.tools.executor import ToolExecutor, ToolResult


def default_registry() -> ToolRegistry:
    """创建一个已注册全部内置工具的注册表。"""
    return register_builtin_tools(ToolRegistry())


__all__ = [
    "RiskLevel", "ToolContext", "ToolRegistry", "ToolSpec",
    "ToolExecutor", "ToolResult", "default_registry", "register_builtin_tools", "safe_eval",
]
