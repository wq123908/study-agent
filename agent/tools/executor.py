"""工具执行器：参数校验、并发限流、超时熔断与结果截断。"""
from __future__ import annotations 

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable
from pydantic import ValidationError
from agent.message import ToolCallItem
from agent.tools.base import RiskLevel, ToolContext, ToolRegistry

logger = logging.getLogger(__name__)
FaultInjector = Callable[[str], BaseException | None]  # 故障注入钩子（供阶段 12 混沌评测使用）

@dataclass
class ToolResult:
    tool_call_id: str
    name: str
    content: str
    ok: bool
    error_type: str | None = None
    duration_ms: float = 0.0

class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        default_timeout: float = 15.0,
        max_concurrency: int = 5,
        max_output_chars: int = 4000,
        fault_injector: FaultInjector | None = None,
    ) -> None:
        self.registry = registry
        self.default_timeout = default_timeout
        self.max_output_chars = max_output_chars
        self.fault_injector = fault_injector
        self._semaphore = asyncio.Semaphore(max_concurrency)  # 限制同时执行的工具总数

    def openai_schemas(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        return self.registry.openai_schemas(allowed)
        
    def risk_of(self, name: str) -> RiskLevel | None:
        spec = self.registry.get(name)
        return spec.risk_level if spec else None

    def is_high_risk(self, name: str) -> bool:
        return self.risk_of(name) == RiskLevel.HIGH_RISK
        
    def _truncate(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        omitted = len(text) - self.max_output_chars
        return text[: self.max_output_chars] + f"\n[输出过长，已截断 {omitted} 个字符]"

