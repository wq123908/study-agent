"""组装工厂：根据 Config 一站式构建 Agent（CLI / API / 评测共用）。"""
from __future__ import annotations

from agent.config import Config
from agent.engine.core import Agent
from agent.llm.provider import AsyncLLM, LLMClient
from agent.memory import (
    ContextWindowBuilder,
    JsonFileSessionStore,
    LongTermMemory,
    MemoryManager,
    SessionStore,
    Summarizer,
)
from agent.observability.tracer import JsonlTraceExporter, TraceExporter, Tracer
from agent.tools import ToolExecutor, ToolRegistry, default_registry
from agent.tools.executor import FaultInjector

DEFAULT_SYSTEM_PROMPT = (
    "你是小助手，一个由 DeepSeek 模型驱动的中文 AI 助手。"
    "如果有人问你的身份或底层模型，如实说明你是基于 DeepSeek 的助手，不要声称自己是其他公司的模型。"
    "回答简洁，一般不超过三句话。"
    "涉及时间、日期或数学计算时，必须调用工具获取准确结果，不要猜测。"
    "用户明确要求你记住某件事时，调用 remember_fact 工具。"
    "工具返回错误时，根据错误提示修正参数后重试；不要编造工具没有返回的信息。"
)


def build_agent(
    config: Config,
    *,
    llm: LLMClient | None = None,
    registry: ToolRegistry | None = None,
    store: SessionStore | None = None,
    long_term: LongTermMemory | None = None,
    exporters: list[TraceExporter] | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    background_summary: bool = True,
    fault_injector: FaultInjector | None = None,
) -> Agent:
    llm = llm or AsyncLLM(config)
    memory = MemoryManager(
        store=store or JsonFileSessionStore(config.sessions_dir),
        window=ContextWindowBuilder(max_tokens=config.context_max_tokens),
        summarizer=Summarizer(llm),
        long_term=long_term if long_term is not None else LongTermMemory(config.long_term_path),
        summary_trigger_tokens=config.summary_trigger_tokens,
        long_term_top_k=config.long_term_top_k,
        background_summary=background_summary,
    )
    executor = ToolExecutor(
        registry or default_registry(),
        default_timeout=config.tool_timeout,
        max_concurrency=config.tool_max_concurrency,
        max_output_chars=config.tool_max_output_chars,
        fault_injector=fault_injector,
    )
    tracer = Tracer(exporters if exporters is not None else [JsonlTraceExporter(config.traces_dir)])
    return Agent(
        llm=llm,
        memory=memory,
        executor=executor,
        system_prompt=system_prompt,
        max_steps=config.max_steps,
        max_input_chars=config.max_input_chars,
        tracer=tracer,
        workspace_dir=config.workspace_dir,
    )
