"""异步 LLM 客户端：流式聚合（文本 / 思考 / 分片 tool_calls）+ 指数退避重试 + 备用模型降级。"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Protocol

import openai
from openai import AsyncOpenAI

from agent.config import Config
from agent.message import ASSISTANT, Message, ToolCallItem
from agent.observability.tracer import current_trace, span

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class LLMError(RuntimeError):
    """模型调用最终失败（重试与降级均耗尽）。"""


@dataclass
class LLMEvent:
    """流式事件：content_delta / reasoning_delta / message_complete"""
    type: str
    delta: str = ""
    message: Message | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""


class LLMClient(Protocol):
    """引擎依赖的最小接口，便于替换供应商或在测试中注入假模型。"""

    def stream_chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[LLMEvent]: ...

    async def complete(self, messages: list[dict[str, Any]], *, temperature: float | None = None) -> str: ...


def _usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        data = usage.model_dump(exclude_none=True)
    else:
        data = dict(usage)
    # 只保留扁平的数值字段（嵌套的 details 不参与累加）
    return {k: v for k, v in data.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}


class AsyncLLM:
    def __init__(self, config: Config, client: AsyncOpenAI | None = None) -> None:
        self.config = config
        self.client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
            max_retries=0,  # 重试与降级由本类显式控制
        )

    def _models(self) -> list[str]:
        models = [self.config.model]
        if self.config.fallback_model and self.config.fallback_model != self.config.model:
            models.append(self.config.fallback_model)
        return models

    async def _backoff(self, attempt: int) -> None:
        delay = min(8.0, 0.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.25)
        await asyncio.sleep(delay)

    # ------------------------------------------------------------------ 流式
    async def stream_chat(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> AsyncIterator[LLMEvent]:
        last_error: BaseException | None = None
        for model in self._models():
            for attempt in range(1, self.config.max_retries + 1):
                emitted = False
                with span("llm", "chat.completions", input={"messages": len(messages)},
                          model=model, attempt=attempt) as sp:
                    try:
                        async for event in self._stream_once(model, messages, tools, sp):
                            emitted = True
                            yield event
                        return
                    except RETRYABLE_ERRORS as exc:
                        last_error = exc
                        sp.set_error(f"{type(exc).__name__}: {exc}")
                        if emitted:
                            # 已经向下游推送过增量内容，重试会导致内容重复，直接失败
                            raise LLMError(f"流式输出中断: {exc}") from exc
                        logger.warning("模型 %s 第 %d 次请求失败: %s", model, attempt, exc)
                if attempt < self.config.max_retries:
                    await self._backoff(attempt)
            logger.error("模型 %s 重试耗尽，尝试降级", model)
        raise LLMError(f"LLM 请求失败（已重试并降级）: {last_error}")

    async def _stream_once(
        self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, sp
    ) -> AsyncIterator[LLMEvent]:
        started = time.perf_counter()
        first_token_at: float | None = None
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.config.temperature,
            tools=tools or None,          # 空列表必须转为 None，否则接口报错
            stream=True,
            stream_options={"include_usage": True},
        )

        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_buffer: dict[int, dict[str, str]] = {}
        usage: dict[str, Any] = {}
        finish_reason: str | None = None

        async for chunk in stream:
            if getattr(chunk, "usage", None):
                usage = _usage_to_dict(chunk.usage)
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            finish_reason = choice.finish_reason or finish_reason
            delta = choice.delta
            if delta is None:
                continue

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                first_token_at = first_token_at or time.perf_counter()
                reasoning_parts.append(reasoning)
                yield LLMEvent(type="reasoning_delta", delta=reasoning, model=model)

            if delta.content:
                first_token_at = first_token_at or time.perf_counter()
                content_parts.append(delta.content)
                yield LLMEvent(type="content_delta", delta=delta.content, model=model)

            # tool_calls 以分片形式到达：按 index 聚合 id / name / arguments
            for tc in delta.tool_calls or []:
                first_token_at = first_token_at or time.perf_counter()
                buf = tool_buffer.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    buf["id"] = tc.id
                if tc.function is not None:
                    if tc.function.name:
                        buf["name"] += tc.function.name
                    if tc.function.arguments:
                        buf["arguments"] += tc.function.arguments

        tool_calls = [
            ToolCallItem(
                id=buf["id"] or f"call_{idx}_{int(time.time() * 1000)}",
                name=buf["name"],
                arguments=buf["arguments"] or "{}",
            )
            for idx, buf in sorted(tool_buffer.items())
        ]
        message = Message(
            role=ASSISTANT,
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            reasoning_content="".join(reasoning_parts) or None,
            metadata={"model": model, "finish_reason": finish_reason, "usage": usage},
        )

        ttft = round((first_token_at - started) * 1000, 1) if first_token_at else None
        sp.update(
            output={"content": (message.content or "")[:300], "tool_calls": [tc.name for tc in tool_calls]},
            ttft_ms=ttft, usage=usage, finish_reason=finish_reason,
        )
        yield LLMEvent(type="message_complete", message=message, usage=usage, model=model)

    # ------------------------------------------------------------------ 非流式
    async def complete(self, messages: list[dict[str, Any]], *, temperature: float | None = None) -> str:
        """用于摘要、评测裁判等内部任务的非流式调用。"""
        last_error: BaseException | None = None
        for model in self._models():
            for attempt in range(1, self.config.max_retries + 1):
                with span("llm", "chat.completions.sync", model=model, attempt=attempt) as sp:
                    try:
                        resp = await self.client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=self.config.temperature if temperature is None else temperature,
                        )
                        usage = _usage_to_dict(resp.usage)
                        sp.update(usage=usage)
                        trace = current_trace()
                        if trace is not None:
                            trace.add_usage(usage)
                        return resp.choices[0].message.content or ""
                    except RETRYABLE_ERRORS as exc:
                        last_error = exc
                        sp.set_error(f"{type(exc).__name__}: {exc}")
                if attempt < self.config.max_retries:
                    await self._backoff(attempt)
        raise LLMError(f"LLM 请求失败（已重试并降级）: {last_error}")
