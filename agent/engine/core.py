"""异步 Agent 引擎：流式 ReAct 循环 + 事务性记忆提交 + 并发工具调度 + 死循环护栏 + 人工审批（HITL）。

状态流转::

    IDLE ──chat──▶ THINKING ──tool_calls──▶ EXECUTING_TOOLS ──▶ THINKING ... ──▶ IDLE(done)
                       │                          ▲
                       └─高危工具─▶ WAITING_APPROVAL ─approve/reject─┘

持久化策略：
- 普通对话：整轮成功后一次性提交（原子性），中途失败不会留下孤立的 user 消息；
- 挂起审批：把包含 assistant(tool_calls) 的完整轨迹作为 Checkpoint 落盘，恢复时从断点继续。
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, AsyncIterator

from agent.engine.events import (
    APPROVAL_REQUIRED,
    APPROVAL_RESOLVED,
    CONTENT_DELTA,
    DONE,
    RUN_START,
    STEP_START,
    THINKING_DELTA,
    TOOL_CALL_RESULT,
    TOOL_CALL_START,
    AgentEvent,
    error_event,
)
from agent.engine.guardrails import LoopGuard, validate_user_input
from agent.llm.provider import LLMClient, LLMError
from agent.memory.manager import MemoryManager
from agent.memory.store import InvalidSessionId
from agent.message import ASSISTANT, TOOL, USER, Message, ToolCallItem
from agent.observability.tracer import Trace, Tracer, activate_trace, current_trace, deactivate_trace, span
from agent.state import PendingApproval, RunStatus, SessionState
from agent.tools.base import ToolContext
from agent.tools.executor import ToolExecutor

logger = logging.getLogger(__name__)

DUPLICATE_CALL_NOTICE = "[护栏] 你已经用完全相同的参数调用过该工具，结果见上文。请直接基于已有结果回答，或更换思路。"
REJECTED_NOTICE = "[已拒绝] 用户拒绝执行该操作。请告知用户该操作未执行，并询问是否需要其他帮助。"
FINALIZE_NOTICE = "[系统提示] 已达到工具调用上限，请停止调用工具，直接基于已有信息给出最终回答。"


class Agent:
    def __init__(
        self,
        *,
        llm: LLMClient,
        memory: MemoryManager,
        executor: ToolExecutor,
        system_prompt: str,
        name: str = "小助手",
        max_steps: int = 8,
        max_input_chars: int = 8000,
        tracer: Tracer | None = None,
        workspace_dir: str | Path | None = None,
    ) -> None:
        self.llm = llm
        self.memory = memory
        self.executor = executor
        self.system_prompt = system_prompt
        self.name = name
        self.max_steps = max_steps
        self.max_input_chars = max_input_chars
        self.tracer = tracer or Tracer()
        self.workspace_dir = Path(workspace_dir) if workspace_dir else None
        self._running: set[str] = set()   # 单进程内的会话互斥（多实例部署需换成分布式锁）

    # ================================================================== 公共 API
    async def chat_stream(
        self, session_id: str, user_input: str, user_id: str = "default"
    ) -> AsyncIterator[AgentEvent]:
        """处理一条用户输入，以事件流形式返回整个推理过程。"""
        text = (user_input or "").strip()
        if (problem := validate_user_input(text, self.max_input_chars)) is not None:
            yield error_event("invalid_input", problem)
            return

        async for event in self._guarded_run("agent.chat", session_id, user_id, text,
                                             self._chat_body(session_id, user_id, text)):
            yield event

    async def resume(
        self,
        session_id: str,
        approve: bool | None = None,
        decisions: dict[str, bool] | None = None,
        user_id: str = "default",
    ) -> AsyncIterator[AgentEvent]:
        """对挂起的高危工具做出审批决定并继续执行。

        approve=True/False 表示全部批准/拒绝；decisions 可按 tool_call_id 单独指定（优先级更高）。
        """
        async for event in self._guarded_run("agent.resume", session_id, user_id,
                                             {"approve": approve, "decisions": decisions},
                                             self._resume_body(session_id, user_id, approve, decisions)):
            yield event

    async def chat(self, session_id: str, user_input: str, user_id: str = "default") -> dict[str, Any]:
        """非流式便捷接口：汇总事件流为最终结果。"""
        return await collect(self.chat_stream(session_id, user_input, user_id))

    async def get_state(self, session_id: str) -> SessionState:
        return await self.memory.load(session_id)

    async def reset(self, session_id: str) -> bool:
        return await self.memory.clear(session_id)

    # ================================================================== 运行框架
    async def _guarded_run(
        self, name: str, session_id: str, user_id: str, trace_input: Any, body: AsyncIterator[AgentEvent]
    ) -> AsyncIterator[AgentEvent]:
        """统一处理：会话互斥、Trace 生命周期、异常兜底。"""
        if session_id in self._running:
            await body.aclose()
            yield error_event("session_busy", "该会话正在处理上一条消息，请稍后再试")
            return

        trace = self.tracer.start_trace(name, session_id=session_id, user_id=user_id, input=trace_input)
        tokens = activate_trace(trace)
        self._running.add(session_id)
        error: str | None = None
        try:
            yield AgentEvent(RUN_START, {"trace_id": trace.trace_id, "session_id": session_id})
            async for event in body:
                if event.type == DONE:
                    event.data.update(
                        trace_id=trace.trace_id,
                        usage=dict(trace.usage),
                        duration_ms=round((time.time() - trace.start) * 1000, 1),
                    )
                    trace.output = event.data.get("content")
                elif event.type == APPROVAL_REQUIRED:
                    event.data["trace_id"] = trace.trace_id
                    trace.attributes["status"] = RunStatus.WAITING_APPROVAL.value
                elif event.type == "error":
                    error = event.data.get("message")
                yield event
        except InvalidSessionId as exc:
            error = str(exc)
            yield error_event("invalid_session_id", str(exc))
        except LLMError as exc:
            error = str(exc)
            logger.error("模型调用失败: %s", exc)
            yield error_event("llm_error", f"模型服务暂时不可用：{exc}", trace_id=trace.trace_id)
        except Exception as exc:  # noqa: BLE001 - 任何异常都转换为事件，不能让服务崩溃
            error = f"{type(exc).__name__}: {exc}"
            logger.exception("Agent 运行异常")
            yield error_event("internal_error", error, trace_id=trace.trace_id)
        finally:
            self._running.discard(session_id)
            self.tracer.finish_trace(trace, error=error)
            deactivate_trace(tokens)

    # ================================================================== 对话主体
    async def _chat_body(self, session_id: str, user_id: str, text: str) -> AsyncIterator[AgentEvent]:
        state = await self.memory.load(session_id, user_id)
        if state.status == RunStatus.WAITING_APPROVAL:
            yield error_event(
                "approval_pending",
                "该会话有待审批的高危操作，请先批准或拒绝后再继续对话",
                pending_tools=self._pending_tools_payload(state),
            )
            return
        state.user_id = user_id
        # 在工作副本上推进，成功后才提交，保证单轮对话的原子性
        working = list(state.messages)
        working.append(Message(role=USER, content=text))
        async for event in self._run_loop(state, working, start_step=1, guard=LoopGuard(), query=text):
            yield event

    async def _resume_body(
        self, session_id: str, user_id: str, approve: bool | None, decisions: dict[str, bool] | None
    ) -> AsyncIterator[AgentEvent]:
        state = await self.memory.load(session_id, user_id)
        pending = state.pending
        if state.status != RunStatus.WAITING_APPROVAL or pending is None:
            yield error_event("no_pending_approval", "该会话没有待审批的操作")
            return
        working = list(state.messages)
        last = working[-1] if working else None
        if last is None or last.role != ASSISTANT or not last.tool_calls:
            yield error_event("corrupted_checkpoint", "检查点数据异常：未找到待执行的工具调用")
            return

        decisions = decisions or {}
        if approve is None and not all(cid in decisions for cid in pending.tool_call_ids):
            yield error_event("decision_required", "请为每个待审批操作给出批准/拒绝决定",
                              pending_tools=self._pending_tools_payload(state))
            return
        rejected = {
            cid for cid in pending.tool_call_ids
            if not decisions.get(cid, bool(approve))
        }
        approved = [cid for cid in pending.tool_call_ids if cid not in rejected]
        yield AgentEvent(APPROVAL_RESOLVED, {"approved": approved, "rejected": sorted(rejected)})

        guard = LoopGuard(seen=pending.seen_signatures)
        state.status, state.pending = RunStatus.IDLE, None
        with span("step", f"step-{pending.step}-resume"):
            async for event in self._execute_calls(
                last.tool_calls, working, state, blocked=set(pending.blocked_ids), rejected=rejected
            ):
                yield event
        # 已产生副作用，立即落盘检查点，避免后续失败导致重复执行已批准的操作
        state.messages = list(working)
        await self.memory.commit(state)

        query = next((m.content or "" for m in reversed(working) if m.role == USER), "")
        async for event in self._run_loop(state, working, start_step=pending.step + 1, guard=guard, query=query):
            yield event

    # ================================================================== ReAct 循环
    async def _run_loop(
        self, state: SessionState, working: list[Message], *, start_step: int, guard: LoopGuard, query: str
    ) -> AsyncIterator[AgentEvent]:
        tools = self.executor.openai_schemas()
        step = start_step - 1
        for step in range(start_step, self.max_steps + 1):
            with span("step", f"step-{step}"):
                yield AgentEvent(STEP_START, {"step": step})
                assistant: Message | None = None
                async for event in self._call_llm(state, working, query, tools):
                    if isinstance(event, Message):
                        assistant = event
                    else:
                        yield event
                assert assistant is not None
                working.append(assistant)

                if not assistant.tool_calls:
                    await self._commit_idle(state, working)
                    yield AgentEvent(DONE, {"content": assistant.content or "", "steps": step, "truncated": False})
                    return

                blocked = guard.check(assistant.tool_calls)
                if blocked:
                    logger.warning("检测到重复工具调用 %d 个（累计违规 %d 次）", len(blocked), guard.violations)

                high_risk = [
                    tc for tc in assistant.tool_calls
                    if tc.id not in blocked and self.executor.is_high_risk(tc.name)
                ]
                if high_risk:
                    state.messages = list(working)
                    state.status = RunStatus.WAITING_APPROVAL
                    state.pending = PendingApproval(
                        step=step,
                        tool_call_ids=[tc.id for tc in high_risk],
                        blocked_ids=sorted(blocked),
                        seen_signatures=sorted(guard.seen),
                    )
                    await self.memory.commit(state)
                    yield AgentEvent(APPROVAL_REQUIRED, {
                        "step": step,
                        "pending_tools": self._pending_tools_payload(state),
                        "content": assistant.content or "",
                    })
                    return

                async for event in self._execute_calls(assistant.tool_calls, working, state, blocked=blocked):
                    yield event

                if guard.tripped:
                    logger.warning("重复调用次数达到上限，强制收尾")
                    break

        # 步数耗尽或护栏触发：不带工具再请求一次，强制模型基于已有信息总结
        with span("step", "finalize"):
            yield AgentEvent(STEP_START, {"step": step + 1, "finalize": True})
            assistant = None
            async for event in self._call_llm(state, working, query, tools=None, extra_notice=FINALIZE_NOTICE):
                if isinstance(event, Message):
                    assistant = event
                else:
                    yield event
            assert assistant is not None
            assistant.tool_calls = []  # 理论上不会出现；防御性清空，保证落盘协议合法
            working.append(assistant)
            await self._commit_idle(state, working)
            yield AgentEvent(DONE, {"content": assistant.content or "", "steps": step + 1, "truncated": True})

    async def _call_llm(
        self,
        state: SessionState,
        working: list[Message],
        query: str,
        tools: list[dict[str, Any]] | None,
        extra_notice: str | None = None,
    ) -> AsyncIterator[AgentEvent | Message]:
        bundle = self.memory.build_context(state, working, self.system_prompt, query)
        messages = bundle.messages
        if extra_notice:
            messages = messages + [{"role": USER, "content": extra_notice}]
        completed: Message | None = None
        async for ev in self.llm.stream_chat(messages, tools):
            if ev.type == "content_delta":
                yield AgentEvent(CONTENT_DELTA, {"delta": ev.delta})
            elif ev.type == "reasoning_delta":
                yield AgentEvent(THINKING_DELTA, {"delta": ev.delta})
            elif ev.type == "message_complete":
                completed = ev.message
                if (tr := current_trace()) is not None and ev.usage:
                    tr.add_usage(ev.usage)
        if completed is None:
            raise LLMError("模型未返回完整消息")
        yield completed

    async def _execute_calls(
        self,
        calls: list[ToolCallItem],
        working: list[Message],
        state: SessionState,
        *,
        blocked: set[str],
        rejected: set[str] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        rejected = rejected or set()
        runnable = [c for c in calls if c.id not in blocked and c.id not in rejected]
        for c in calls:
            status = "blocked" if c.id in blocked else "rejected" if c.id in rejected else "running"
            yield AgentEvent(TOOL_CALL_START, {
                "tool_call_id": c.id, "name": c.name, "arguments": c.arguments, "status": status,
            })

        ctx = ToolContext(
            session_id=state.session_id,
            user_id=state.user_id,
            workspace_dir=self.workspace_dir,
            long_term=self.memory.long_term,
        )
        results = {r.tool_call_id: r for r in await self.executor.execute_batch(runnable, ctx)}

        for c in calls:
            if c.id in blocked:
                content, ok, error_type, duration = DUPLICATE_CALL_NOTICE, False, "duplicate_call", 0.0
            elif c.id in rejected:
                content, ok, error_type, duration = REJECTED_NOTICE, False, "rejected", 0.0
            else:
                r = results[c.id]
                content, ok, error_type, duration = r.content, r.ok, r.error_type, r.duration_ms
            working.append(Message(
                role=TOOL, tool_call_id=c.id, name=c.name, content=content,
                metadata={"ok": ok, "error_type": error_type, "duration_ms": duration},
            ))
            yield AgentEvent(TOOL_CALL_RESULT, {
                "tool_call_id": c.id, "name": c.name, "ok": ok, "error_type": error_type,
                "duration_ms": duration, "output_preview": content[:200],
            })

    # ================================================================== 辅助
    async def _commit_idle(self, state: SessionState, working: list[Message]) -> None:
        state.messages = list(working)
        state.status, state.pending = RunStatus.IDLE, None
        await self.memory.commit(state)

    def _pending_tools_payload(self, state: SessionState) -> list[dict[str, Any]]:
        if not state.pending or not state.messages:
            return []
        last = state.messages[-1]
        wanted = set(state.pending.tool_call_ids)
        return [
            {
                "tool_call_id": tc.id,
                "name": tc.name,
                "arguments": tc.arguments,
                "risk_level": getattr(self.executor.risk_of(tc.name), "value", "UNKNOWN"),
            }
            for tc in last.tool_calls if tc.id in wanted
        ]


async def collect(events: AsyncIterator[AgentEvent]) -> dict[str, Any]:
    """把事件流汇总为一个结果字典（用于非流式接口、评测与测试）。"""
    result: dict[str, Any] = {
        "status": "error", "content": "", "tool_calls": [], "tool_results": [],
        "pending_tools": [], "error": None, "trace_id": None, "steps": 0, "usage": {},
    }
    parts: list[str] = []
    async for ev in events:
        data = ev.data
        if ev.type == RUN_START:
            result["trace_id"] = data.get("trace_id")
        elif ev.type == CONTENT_DELTA:
            parts.append(data["delta"])
        elif ev.type == TOOL_CALL_START:
            result["tool_calls"].append({k: data[k] for k in ("tool_call_id", "name", "arguments", "status")})
        elif ev.type == TOOL_CALL_RESULT:
            result["tool_results"].append(data)
        elif ev.type == APPROVAL_REQUIRED:
            result.update(status="waiting_approval", pending_tools=data["pending_tools"])
        elif ev.type == DONE:
            result.update(status="done", content=data["content"], steps=data["steps"],
                          usage=data.get("usage", {}), truncated=data.get("truncated", False),
                          duration_ms=data.get("duration_ms"))
        elif ev.type == "error":
            result.update(status="error", error={"code": data.get("code"), "message": data.get("message")})
    if result["status"] != "done":
        result["content"] = "".join(parts)
    return result
