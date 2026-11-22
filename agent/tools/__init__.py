"""工具子包（将在 9.4 导出完整注册表与并发执行器）。""" 
"""声明式安全工具包：统一导出注册表、执行器、风险分级与默认工具集。"""
from agent.tools.base import (
    RiskLevel,
    ToolContext,
    ToolRegistry,
    ToolSpec,
)
from agent.tools.builtin import (
    register_builtin_tools,
    safe_eval,
)
from agent.tools.executor import (
    ToolExecutor,
    ToolResult,
)


def default_registry() -> ToolRegistry:
    """创建一个已注册全部内置工具的注册表。"""
    return register_builtin_tools(ToolRegistry())


__all__ = [
    "RiskLevel",
    "ToolContext",
    "ToolRegistry",
    "ToolSpec",
    "ToolExecutor",
    "ToolResult",
    "default_registry",
    "register_builtin_tools",
    "safe_eval",
]