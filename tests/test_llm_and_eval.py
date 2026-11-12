"""测试 AsyncLLM 流式分片拼接/重试/主备模型降级、Trace 瀑布图与自动化评测集。"""
from __future__ import annotations

from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from agent.config import Config, ConfigError
from agent.llm.provider import AsyncLLM, LLMError
from agent.observability.tracer import JsonlTraceExporter, Tracer, activate_trace, deactivate_trace, span
from agent.observability.view import main as view_main
from eval.run_eval import run_suite


def _chunk(content=None, reasoning=None, tool_calls=None, finish_reason=None, usage=None):
    delta = SimpleNamespace(content=content, reasoning_content=reasoning, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def _tc_delta(index: int, id: str | None = None, name: str | None = None, arguments: str | None = None):
    fn = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=id, function=fn)


class FakeCompletions:
    def __init__(self, behaviors: list):
        self.behaviors = list(behaviors)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        behavior = self.behaviors.pop(0)
        if isinstance(behavior, BaseException):
            raise behavior
        if kwargs.get("stream"):
            async def _gen():
                for c in behavior:
                    yield c
            return _gen()
        return behavior


def _make_fake_client(behaviors: list):
    completions = FakeCompletions(behaviors)
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


async def test_async_llm_assembles_fragmented_tool_calls_and_reasoning():
    chunks = [
        _chunk(reasoning="先思考"),
        _chunk(content="好，"),
        _chunk(tool_calls=[_tc_delta(0, id="call_1", name="cal", arguments='{"expr')]),
        _chunk(tool_calls=[_tc_delta(0, name="culator", arguments='ession": "1+2"}')], finish_reason="tool_calls"),
        SimpleNamespace(choices=[], usage={"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12}),
    ]
    client, _ = _make_fake_client([chunks])
    llm = AsyncLLM(Config(api_key="k", max_retries=2), client=client)  # type: ignore[arg-type]

    events = [ev async for ev in llm.stream_chat([{"role": "user", "content": "hi"}])]
    types = [e.type for e in events]
    assert types == ["reasoning_delta", "content_delta", "message_complete"]
    final = events[-1].message
    assert final.reasoning_content == "先思考"
    assert final.content == "好，"
    assert len(final.tool_calls) == 1
    assert final.tool_calls[0].id == "call_1"
    assert final.tool_calls[0].name == "calculator"
    assert final.tool_calls[0].arguments == '{"expression": "1+2"}'
    assert events[-1].usage["total_tokens"] == 12


async def test_async_llm_retries_and_falls_back_to_secondary_model(monkeypatch):
    async def _fast_backoff(self, attempt):
        return None

    monkeypatch.setattr(AsyncLLM, "_backoff", _fast_backoff)
    req = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    timeout_err = openai.APITimeoutError(request=req)

    # 主模型重试 2 次均超时 → 降级到备用模型成功
    ok_chunks = [_chunk(content="备用模型回答", finish_reason="stop")]
    client, completions = _make_fake_client([timeout_err, timeout_err, ok_chunks])
    cfg = Config(api_key="k", model="primary-m", fallback_model="backup-m", max_retries=2)
    llm = AsyncLLM(cfg, client=client)  # type: ignore[arg-type]

    events = [ev async for ev in llm.stream_chat([{"role": "user", "content": "hi"}])]
    assert events[-1].message.content == "备用模型回答"
    assert [c["model"] for c in completions.calls] == ["primary-m", "primary-m", "backup-m"]


async def test_async_llm_raises_when_all_models_exhausted(monkeypatch):
    monkeypatch.setattr(AsyncLLM, "_backoff", lambda self, attempt: __import__("asyncio").sleep(0))
    req = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    err = openai.APIConnectionError(request=req)
    client, _ = _make_fake_client([err, err])
    llm = AsyncLLM(Config(api_key="k", max_retries=2), client=client)  # type: ignore[arg-type]

    with pytest.raises(LLMError):
        _ = [ev async for ev in llm.stream_chat([{"role": "user", "content": "hi"}])]


def test_trace_jsonl_exporter_and_cli_waterfall(tmp_path, capsys):
    exporter = JsonlTraceExporter(tmp_path)
    tracer = Tracer([exporter])
    tr = tracer.start_trace("agent.chat", session_id="s1", input="测试问题")
    tokens = activate_trace(tr)
    with span("step", "step-1"):
        with span("llm", "chat", ttft_ms=42.0):
            pass
    deactivate_trace(tokens)
    tracer.finish_trace(tr, output="测试回答")

    assert view_main(["--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "step:step-1" in out and "ttft=42.0ms" in out
    assert view_main(["--dir", str(tmp_path), "--list", "5"]) == 0


def test_config_validation():
    with pytest.raises(ConfigError):
        Config(api_key="k", max_steps=0).validate()
    with pytest.raises(ConfigError):
        Config(api_key="k", context_max_tokens=100).validate()


async def test_golden_evaluation_suite_passes_all_sla_gates():
    summary = await run_suite()
    assert summary["passed"] is True
    assert summary["trajectory_recall"] >= 0.95
    assert summary["illegal_tool_rate"] == 0.0
    assert summary["avg_faithfulness"] >= 4.5
    assert summary["resilience_rate"] >= 0.85
