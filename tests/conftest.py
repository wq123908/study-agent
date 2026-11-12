"""测试夹具：可编排的假模型 + 内存存储，全部离线运行。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator

import pytest

from agent.config import Config
from agent.factory import build_agent
from agent.llm.provider import LLMEvent
from agent.memory import InMemorySessionStore, LongTermMemory
from agent.message import ASSISTANT, Message, ToolCallItem
from agent.observability.tracer import InMemoryTraceExporter


def tool_call(name: str, args: dict | str | None = None, call_id: str | None = None) -> ToolCallItem:
    arguments = args if isinstance(args, str) else json.dumps(args or {}, ensure_ascii=False)
    return ToolCallItem(id=call_id or f"call_{name}_{abs(hash(arguments)) % 10_000}", name=name, arguments=arguments)


class ScriptedLLM:
    """按顺序回放脚本：str → 文本回答；list[ToolCallItem] → 工具调用；Exception → 抛出。"""

    def __init__(self, script: list[Any] | None = None, summary: str = "摘要") -> None:
        self.script = list(script or [])
        self.summary = summary
        self.requests: list[dict[str, Any]] = []
        self.complete_calls: list[list[dict[str, Any]]] = []

    def push(self, *items: Any) -> None:
        self.script.extend(items)

    async def stream_chat(self, messages, tools=None) -> AsyncIterator[LLMEvent]:
        self.requests.append({"messages": messages, "tools": tools})
        if not self.script:
            raise AssertionError("ScriptedLLM 脚本已耗尽")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, str):
            for i in range(0, len(item), 4):
                yield LLMEvent(type="content_delta", delta=item[i:i + 4])
            yield LLMEvent(type="message_complete", message=Message(role=ASSISTANT, content=item),
                           usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15})
            return
        calls = list(item)
        yield LLMEvent(type="message_complete", message=Message(role=ASSISTANT, content=None, tool_calls=calls),
                       usage={"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13})

    async def complete(self, messages, *, temperature=None) -> str:
        self.complete_calls.append(messages)
        return self.summary


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(api_key="test", data_dir=tmp_path / "data", max_steps=4)


@pytest.fixture
def make_agent(config: Config):
    def _make(script: list[Any] | None = None, **kwargs):
        llm = kwargs.pop("llm", None) or ScriptedLLM(script)
        exporter = InMemoryTraceExporter()
        agent = build_agent(
            config,
            llm=llm,
            store=kwargs.pop("store", None) or InMemorySessionStore(),
            long_term=kwargs.pop("long_term", None) or LongTermMemory(None),
            exporters=[exporter],
            background_summary=kwargs.pop("background_summary", False),
            **kwargs,
        )
        agent.test_llm = llm            # type: ignore[attr-defined]
        agent.test_exporter = exporter  # type: ignore[attr-defined]
        return agent
    return _make
