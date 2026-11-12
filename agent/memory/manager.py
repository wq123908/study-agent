"""记忆门面：协调 L1 会话存储、上下文窗口、L2 滚动摘要与 L3 长期记忆。"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from agent.llm.token_counter import count_messages_tokens, count_text_tokens
from agent.memory.long_term import LongTermMemory
from agent.memory.store import SessionStore, validate_session_id
from agent.memory.summarizer import Summarizer
from agent.memory.window import ContextWindowBuilder
from agent.message import SYSTEM, Message
from agent.observability.tracer import span
from agent.state import SessionState

logger = logging.getLogger(__name__)


@dataclass
class ContextBundle:
    messages: list[dict[str, Any]]           # 直接发给模型的消息
    window_start: int                        # 本次窗口在 working 中的起点
    tokens: int                              # 估算的总 Token 数
    facts: list[str] = field(default_factory=list)


class MemoryManager:
    def __init__(
        self,
        store: SessionStore,
        window: ContextWindowBuilder,
        summarizer: Summarizer | None = None,
        long_term: LongTermMemory | None = None,
        summary_trigger_tokens: int = 1500,
        long_term_top_k: int = 3,
        background_summary: bool = True,
    ) -> None:
        self.store = store
        self.window = window
        self.summarizer = summarizer
        self.long_term = long_term
        self.summary_trigger_tokens = summary_trigger_tokens
        self.long_term_top_k = long_term_top_k
        self.background_summary = background_summary
        self._locks: dict[str, asyncio.Lock] = {}
        self._tasks: set[asyncio.Task] = set()

    def lock(self, session_id: str) -> asyncio.Lock:
        return self._locks.setdefault(session_id, asyncio.Lock())

    # ------------------------------------------------------------------ 会话
    async def load(self, session_id: str, user_id: str = "default") -> SessionState:
        validate_session_id(session_id)
        state = await self.store.load(session_id)
        return state or SessionState(session_id=session_id, user_id=user_id)

    async def clear(self, session_id: str) -> bool:
        async with self.lock(session_id):
            return await self.store.delete(session_id)

    async def commit(self, state: SessionState) -> None:
        """持久化一轮完整结果；保留后台摘要任务已写入的摘要字段（避免互相覆盖）。"""
        async with self.lock(state.session_id):
            stored = await self.store.load(state.session_id)
            if (
                stored is not None
                and stored.created_at == state.created_at
                and stored.summarized_upto > state.summarized_upto
            ):
                state.summary, state.summarized_upto = stored.summary, stored.summarized_upto
            state.updated_at = time.time()
            await self.store.save(state)
        self._schedule_summary(state.session_id)

    # ------------------------------------------------------------------ 上下文
    def build_context(
        self, state: SessionState, working: list[Message], system_prompt: str, query: str = ""
    ) -> ContextBundle:
        with span("memory", "build_context", input={"messages": len(working)}) as sp:
            system_text = system_prompt
            if state.summary:
                system_text += f"\n\n【早期对话摘要】\n{state.summary}"
            facts: list[str] = []
            if self.long_term is not None:
                facts = self.long_term.search(state.user_id, query, top_k=self.long_term_top_k)
                if facts:
                    system_text += "\n\n【关于该用户的长期记忆】\n" + "\n".join(f"- {f}" for f in facts)

            reserved = count_text_tokens(system_text) + 4
            selection = self.window.select(working, reserved_tokens=reserved)
            messages = [{"role": SYSTEM, "content": system_text}] + [m.to_dict() for m in selection.messages]
            tokens = reserved + selection.tokens
            sp.update(
                output={"sent_messages": len(messages)},
                window_start=selection.start, tokens=tokens, facts=len(facts),
                has_summary=bool(state.summary),
            )
        return ContextBundle(messages=messages, window_start=selection.start, tokens=tokens, facts=facts)

    # ------------------------------------------------------------------ L2 摘要
    def _pending_summary_range(self, state: SessionState) -> tuple[int, int] | None:
        reserved = count_text_tokens(state.summary) + 200
        start = self.window.select(state.messages, reserved_tokens=reserved).start
        begin = state.summarized_upto
        if start <= begin:
            return None
        if count_messages_tokens(state.messages[begin:start]) < self.summary_trigger_tokens:
            return None
        return begin, start

    def _schedule_summary(self, session_id: str) -> None:
        if self.summarizer is None:
            return
        if self.background_summary:
            task = asyncio.create_task(self.summarize_if_needed(session_id))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def summarize_if_needed(self, session_id: str) -> bool:
        """若滑出窗口且未摘要的消息超过阈值，则生成新摘要。返回是否更新了摘要。"""
        if self.summarizer is None:
            return False
        state = await self.store.load(session_id)
        if state is None:
            return False
        rng = self._pending_summary_range(state)
        if rng is None:
            return False
        begin, end = rng
        try:
            with span("memory", "summarize", input={"messages": end - begin}):
                summary = await self.summarizer.summarize(state.summary, state.messages[begin:end])
        except Exception:  # noqa: BLE001 - 摘要失败不影响主流程，下次再试
            logger.exception("会话 %s 摘要生成失败", session_id)
            return False

        async with self.lock(session_id):
            fresh = await self.store.load(session_id)
            if (
                fresh is None
                or fresh.created_at != state.created_at
                or fresh.summarized_upto != state.summarized_upto
                or len(fresh.messages) < end
            ):
                return False
            fresh.summary, fresh.summarized_upto = summary, end
            await self.store.save(fresh)
        logger.info("会话 %s 已更新滚动摘要（覆盖前 %d 条消息）", session_id, end)
        return True

    async def wait_background(self) -> None:
        if self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)
