"""上下文窗口构建：按 Token 预算、以“轮次”为原子单位裁剪，保证工具调用链永不被截断。

一个“轮次”从一条 user 消息开始，包含其后所有 assistant(tool_calls) / tool / assistant 消息。
以轮次为单位保留，窗口起点天然是合法的会话边界，不会出现孤立的 role="tool"。
"""
from __future__ import annotations

from dataclasses import dataclass

from agent.llm.token_counter import count_message_tokens
from agent.message import ASSISTANT, SYSTEM, TOOL, USER, Message

MISSING_TOOL_RESULT = "[系统] 该工具调用未执行或结果缺失。"


@dataclass
class WindowSelection:
    start: int                 # 保留区间在原列表中的起始下标
    messages: list[Message]    # 已清洗、可直接发送的消息（不含 system）
    tokens: int


def turn_starts(messages: list[Message]) -> list[int]:
    starts = [i for i, m in enumerate(messages) if m.role == USER]
    if messages and (not starts or starts[0] != 0):
        starts.insert(0, 0)
    return starts


def sanitize(messages: list[Message]) -> list[Message]:
    """修复协议层面不合法的序列：
    - 丢弃 system 消息（system 由构建器统一注入）
    - 丢弃没有对应 assistant(tool_calls) 的孤立 tool 消息
    - 为缺少结果的 tool_call 补齐占位结果（否则 API 会 400）
    """
    result: list[Message] = []
    open_ids: list[str] = []

    def close_open() -> None:
        for call_id in open_ids:
            result.append(Message(role=TOOL, tool_call_id=call_id, content=MISSING_TOOL_RESULT))
        open_ids.clear()

    for msg in messages:
        if msg.role == SYSTEM:
            continue
        if msg.role == TOOL:
            if msg.tool_call_id in open_ids:
                open_ids.remove(msg.tool_call_id)
                result.append(msg)
            continue
        close_open()
        result.append(msg)
        if msg.role == ASSISTANT and msg.tool_calls:
            open_ids.extend(tc.id for tc in msg.tool_calls)
    close_open()
    return result


class ContextWindowBuilder:
    def __init__(self, max_tokens: int = 6000) -> None:
        self.max_tokens = max_tokens

    def select(self, messages: list[Message], reserved_tokens: int = 0) -> WindowSelection:
        """从最新轮次向前累加，直到超出预算；最新一轮始终保留。"""
        if not messages:
            return WindowSelection(start=0, messages=[], tokens=0)

        budget = max(0, self.max_tokens - reserved_tokens)
        starts = turn_starts(messages)
        bounds = list(zip(starts, starts[1:] + [len(messages)]))

        used = 0
        start = len(messages)
        for begin, end in reversed(bounds):
            turn_tokens = sum(count_message_tokens(m) for m in messages[begin:end])
            if used + turn_tokens > budget and start < len(messages):
                break
            used += turn_tokens
            start = begin

        return WindowSelection(start=start, messages=sanitize(messages[start:]), tokens=used)
