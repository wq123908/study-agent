"""异步 LLM 客户端：流式聚合、指数退避重试与备用模型降级。"""
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
from agent.observability.tracer import current_trace, span
from agent.message import ASSISTANT, Message, ToolCallItem

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.InternalServerError,
)

class LLMError(RuntimeError):
    """模型调用最终失败（重试与降级均耗尽）。"""

@dataclass
class LLMEvent:
    """流式事件小纸条：content_delta / reasoning_delta / message_complete。"""
    type: str
    delta: str = ""
    message: Message | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    model: str = ""

class LLMClient(Protocol):
    """引擎依赖的最小模型接口，方便替换厂商或单测注入假大脑。"""
    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMEvent]:
        """流式吐出增量事件并在结尾给出完整消息。"""
    
    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
    ) -> str:
        """非流式一次性返回纯文本，用于摘要或内部判断。"""

def _usage_to_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        data = usage.model_dump(exclude_none=True)
    else:
        data = dict(usage)
    return {
        k: v
        for k, v in data.items()
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    }

class AsyncLLM:
    def __init__(
        self,
        config: Config,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self.config = config
        self.client = client or AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.request_timeout,
            max_retries=0,                  # 关掉 SDK 隐式重试，由本类显式控制退避与降级
        )

    def _models(self) -> list[str]:
        models = [self.config.model]
        if self.config.fallback_model and self.config.fallback_model != self.config.model:
            models.append(self.config.fallback_model)
        return models

    async def _backoff(self, attempt: int) -> None:
        delay = min(8.0, 0.5 * 2 ** (attempt - 1)) + random.uniform(0, 0.25)
        await asyncio.sleep(delay)

    async def complete(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
    ) -> str:
        """用于摘要、评测裁判等内部任务的非流式调用。"""
        last_error: BaseException | None = None
        temp = self.config.temperature if temperature is None else temperature
        for model in self._models():
            for attempt in range(1, self.config.max_retries + 1):
                with span(
                    kind="llm",
                    name="chat.completions.sync",
                    model=model,
                    attempt=attempt,
                ) as sp:
                    try:
                        resp = await self.client.chat.completions.create(
                            model=model,
                            messages=messages,
                            temperature=temp,
                        )
                        usage = _usage_to_dict(resp.usage)
                        sp.update(usage=usage)
                        if (trace := current_trace()) is not None:
                            trace.add_usage(usage)
                        return resp.choices[0].message.content or ""
                    except RETRYABLE_ERRORS as exc:
                        last_error = exc
                        sp.set_error(f"{type(exc).__name__}: {exc}")
                if attempt < self.config.max_retries:
                    await self._backoff(attempt)
        raise LLMError(f"LLM 请求失败（已重试并降级）: {last_error}")

    async def _stream_once(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        sp: Any,
    ) -> AsyncIterator[LLMEvent]:
        agg = _StreamAggregator(model)
        stream = await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=self.config.temperature,
            tools=tools or None,            # 空列表必须转成 None，否则接口报错
            stream=True,
            stream_options={"include_usage": True},
        )
        async for chunk in stream:
            for event in agg.feed(chunk):
                yield event
        message, ttft = agg.finalize()
        sp.update(
            output={
                "content": (message.content or "")[:300],
                "tool_calls": [tc.name for tc in message.tool_calls],
            },
            ttft_ms=ttft,
            usage=agg.usage,
            finish_reason=agg.finish_reason,
        )
        yield LLMEvent(
            type="message_complete",
            message=message,
            usage=agg.usage,
            model=model,
        )

    async def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[LLMEvent]:
        last_error: BaseException | None = None
        for model in self._models():
            for attempt in range(1, self.config.max_retries + 1):
                emitted = False
                with span(
                    kind="llm",
                    name="chat.completions",
                    input={"messages": len(messages)},
                    model=model,
                    attempt=attempt,
                ) as sp:
                    try:
                        async for event in self._stream_once(
                            model=model,
                            messages=messages,
                            tools=tools,
                            sp=sp,
                        ):
                            emitted = True
                            yield event
                        return
                    except RETRYABLE_ERRORS as exc:
                        last_error = exc
                        sp.set_error(f"{type(exc).__name__}: {exc}")
                        if emitted:
                            raise LLMError(f"流式输出中断: {exc}") from exc
                        logger.warning(
                            "模型 %s 第 %d 次请求失败: %s",
                            model,
                            attempt,
                            exc,
                        )
                if attempt < self.config.max_retries:
                    await self._backoff(attempt)
            logger.error("模型 %s 重试耗尽，尝试降级", model)
        raise LLMError(f"LLM 请求失败（已重试并降级）: {last_error}")

class _StreamAggregator:
    """流式分片拼图器：边接收 chunk 边产出文本增量，同时缓冲工具碎片。"""
    def __init__(self, model: str) -> None:
        self.model = model
        self.started = time.perf_counter()
        self.first_token_at: float | None = None
        self.content_parts: list[str] = []
        self.reasoning_parts: list[str] = []
        self.tool_buffer: dict[int, dict[str, str]] = {}
        self.usage: dict[str, Any] = {}
        self.finish_reason: str | None = None
    def feed(self, chunk: Any) -> list[LLMEvent]:
        events: list[LLMEvent] = []
        if getattr(chunk, "usage", None):
            self.usage = _usage_to_dict(chunk.usage)
        if not chunk.choices:
            return events
        choice = chunk.choices[0]
        self.finish_reason = choice.finish_reason or self.finish_reason
        delta = choice.delta
        if delta is None:
            return events
        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning:
            self.first_token_at = self.first_token_at or time.perf_counter()
            self.reasoning_parts.append(reasoning)
            events.append(
                LLMEvent(
                    type="reasoning_delta",
                    delta=reasoning,
                    model=self.model,
                )
            )
        if delta.content:
            self.first_token_at = self.first_token_at or time.perf_counter()
            self.content_parts.append(delta.content)
            events.append(
                LLMEvent(
                    type="content_delta",
                    delta=delta.content,
                    model=self.model,
                )
            )
        for tc in delta.tool_calls or []:
            self.first_token_at = self.first_token_at or time.perf_counter()
            buf = self.tool_buffer.setdefault(
                tc.index,
                {"id": "", "name": "", "arguments": ""},
            )
            if tc.id:
                buf["id"] = tc.id
            if tc.function is not None:
                if tc.function.name:
                    buf["name"] += tc.function.name
                if tc.function.arguments:
                    buf["arguments"] += tc.function.arguments
        return events
    
    

    def finalize(self) -> tuple[Message, float | None]:
        tool_calls = [
            ToolCallItem(
                id=buf["id"] or f"call_{idx}_{int(time.time() * 1000)}",
                name=buf["name"],
                arguments=buf["arguments"] or "{}",
            )
            for idx, buf in sorted(self.tool_buffer.items())
        ]
        message = Message(
            role=ASSISTANT,
            content="".join(self.content_parts) or None,
            tool_calls=tool_calls,
            reasoning_content="".join(self.reasoning_parts) or None,
            metadata={
                "model": self.model,
                "finish_reason": self.finish_reason,
                "usage": self.usage,
            },
        )
        ttft = (
            round((self.first_token_at - self.started) * 1000, 1)
            if self.first_token_at
            else None
        )
        return message, ttft