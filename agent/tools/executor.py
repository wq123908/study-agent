"""工具执行器：参数校验 → 并发限流 → 超时熔断 → 异常封装为模型可读的反馈（便于自我纠错）。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable

from pydantic import ValidationError

from agent.message import ToolCallItem
from agent.observability.tracer import span
from agent.tools.base import RiskLevel, ToolContext, ToolRegistry

logger = logging.getLogger(__name__)

# 故障注入钩子：返回一个异常实例则本次调用直接失败（用于混沌评测）
FaultInjector = Callable[[str], BaseException | None]


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
        self._semaphore = asyncio.Semaphore(max_concurrency)

    # ---------- 元信息 ----------
    def openai_schemas(self, allowed: set[str] | None = None) -> list[dict[str, Any]]:
        return self.registry.openai_schemas(allowed)

    def risk_of(self, name: str) -> RiskLevel | None:
        spec = self.registry.get(name)
        return spec.risk_level if spec else None

    def is_high_risk(self, name: str) -> bool:
        return self.risk_of(name) == RiskLevel.HIGH_RISK

    # ---------- 执行 ----------
    def _truncate(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        omitted = len(text) - self.max_output_chars
        return text[: self.max_output_chars] + f"\n...[输出过长，已截断 {omitted} 个字符]"

    async def execute_one(self, call: ToolCallItem, ctx: ToolContext | None = None) -> ToolResult:
        started = time.perf_counter()

        def finish(content: str, ok: bool, error_type: str | None = None) -> ToolResult:
            return ToolResult(
                tool_call_id=call.id,
                name=call.name,
                content=self._truncate(content),
                ok=ok,
                error_type=error_type,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        with span("tool", name=call.name, input={"arguments": call.arguments}) as sp:
            spec = self.registry.get(call.name)
            if spec is None:
                result = finish(
                    f"[工具不存在] 未注册工具 '{call.name}'，可用工具: {', '.join(self.registry.names())}。",
                    ok=False, error_type="unknown_tool",
                )
            else:
                result = await self._run(spec, call, ctx, finish)
            sp.update(output=result.content[:500], ok=result.ok, error_type=result.error_type)
            if not result.ok:
                sp.set_error(result.error_type or "error")
        logger.info("工具 %s 完成 ok=%s 耗时=%.1fms", call.name, result.ok, result.duration_ms)
        return result

    async def _run(self, spec, call: ToolCallItem, ctx: ToolContext | None, finish) -> ToolResult:
        # 1) 解析并校验参数：错误信息原样回填给模型，引导其自我修正
        try:
            raw_args = json.loads(call.arguments or "{}")
            if not isinstance(raw_args, dict):
                raise ValueError("参数必须是 JSON 对象")
            validated = spec.args_model(**raw_args).model_dump()
        except (json.JSONDecodeError, ValueError, ValidationError, TypeError) as exc:
            return finish(
                f"[参数校验失败] 工具 '{spec.name}' 入参有误: {exc}。请对照参数 Schema 修正后重试。",
                ok=False, error_type="invalid_arguments",
            )

        if spec.context_param:
            validated[spec.context_param] = ctx or ToolContext()

        timeout = spec.timeout or self.default_timeout
        async with self._semaphore:
            try:
                if self.fault_injector and (fault := self.fault_injector(spec.name)) is not None:
                    raise fault
                if spec.is_async:
                    coro = spec.func(**validated)
                else:
                    # 注意：线程无法被强制终止，超时后仅放弃等待其结果
                    coro = asyncio.to_thread(spec.func, **validated)
                output = await asyncio.wait_for(coro, timeout=timeout)
                return finish("" if output is None else str(output), ok=True)
            except (asyncio.TimeoutError, TimeoutError):
                return finish(
                    f"[工具执行超时] 工具 '{spec.name}' 超过 {timeout}s 未响应，可稍后重试或换用其他方式。",
                    ok=False, error_type="timeout",
                )
            except Exception as exc:  # noqa: BLE001 - 工具内部任何异常都不能拖垮主循环
                logger.exception("工具 %s 运行异常", spec.name)
                return finish(
                    f"[工具运行异常] 工具 '{spec.name}' 内部报错: {type(exc).__name__}: {exc}",
                    ok=False, error_type="exception",
                )

    async def execute_batch(
        self, calls: list[ToolCallItem], ctx: ToolContext | None = None
    ) -> list[ToolResult]:
        """并发执行同一步内的多个工具调用，结果顺序与输入一致。"""
        return list(await asyncio.gather(*(self.execute_one(c, ctx) for c in calls)))
