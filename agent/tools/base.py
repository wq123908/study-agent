"""声明式工具注册：从函数签名 + 类型注解 + docstring 自动生成 OpenAI Schema 与 Pydantic 校验模型。

用法::

    registry = ToolRegistry()

    @registry.tool(risk_level=RiskLevel.READ_ONLY, timeout=5)
    def add(a: Annotated[int, Field(description="加数")], b: int = 1) -> str:
        '''两数相加'''
        return str(a + b)

声明了 ``ctx: ToolContext`` 的参数会在执行时自动注入，不会暴露给模型。
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, create_model

if TYPE_CHECKING:  # pragma: no cover
    from agent.memory.long_term import LongTermMemory


class RiskLevel(str, Enum):
    READ_ONLY = "READ_ONLY"   # 只读，可自动执行
    WRITE = "WRITE"           # 有副作用但可控，可自动执行
    HIGH_RISK = "HIGH_RISK"   # 高危，必须人工审批（Human-in-the-Loop）


@dataclass
class ToolContext:
    """执行期上下文，按需注入工具函数。"""
    session_id: str = "default"
    user_id: str = "default"
    workspace_dir: Any = None
    long_term: "LongTermMemory | None" = None
    extras: dict[str, Any] = field(default_factory=dict)


class _StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass
class ToolSpec:
    func: Callable[..., Any]
    name: str
    description: str
    args_model: type[BaseModel]
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    timeout: float | None = None          # None 表示使用执行器默认超时
    context_param: str | None = None      # 需要注入 ToolContext 的参数名

    @property
    def is_async(self) -> bool:
        return inspect.iscoroutinefunction(self.func)

    def to_openai_schema(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        for prop in schema.get("properties", {}).values():
            prop.pop("title", None)
        schema.setdefault("properties", {})
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    # ---------- 注册 ----------
    def tool(
        self,
        name: str | None = None,
        description: str | None = None,
        risk_level: RiskLevel | str = RiskLevel.READ_ONLY,
        timeout: float | None = None,
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self.add(func, name=name, description=description, risk_level=risk_level, timeout=timeout)
            return func
        return decorator

    def add(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        description: str | None = None,
        risk_level: RiskLevel | str = RiskLevel.READ_ONLY,
        timeout: float | None = None,
    ) -> ToolSpec:
        tool_name = name or func.__name__
        if tool_name in self._tools:
            raise ValueError(f"工具 {tool_name!r} 重复注册")
        tool_desc = (description or inspect.getdoc(func) or "").strip()
        if not tool_desc:
            raise ValueError(f"工具 {tool_name!r} 缺少描述（docstring 或 description 参数）")

        hints = get_type_hints(func, include_extras=True)
        fields: dict[str, Any] = {}
        context_param: str | None = None
        for param_name, param in inspect.signature(func).parameters.items():
            annotation = hints.get(param_name, str)
            if annotation is ToolContext:
                context_param = param_name
                continue
            if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                raise ValueError(f"工具 {tool_name!r} 不支持 *args/**kwargs 参数")
            default = ... if param.default is inspect.Parameter.empty else param.default
            fields[param_name] = (annotation, default)

        args_model = create_model(f"{tool_name}_Args", __base__=_StrictArgs, **fields)
        spec = ToolSpec(
            func=func,
            name=tool_name,
            description=tool_desc,
            args_model=args_model,
            risk_level=RiskLevel(risk_level),
            timeout=timeout,
            context_param=context_param,
        )
        self._tools[tool_name] = spec
        return spec

    # ---------- 查询 ----------
    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)

    def openai_schemas(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        """allowed 用于按角色/场景动态裁剪可见工具（RBAC 扩展点）。"""
        return [
            spec.to_openai_schema()
            for spec in self._tools.values()
            if allowed is None or spec.name in allowed
        ]
