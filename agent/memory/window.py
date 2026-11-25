"""L1 上下文窗口：按轮次边界裁剪与工具调用链配对修复。"""
from __future__ import annotations

from dataclasses import dataclass

from agent.llm.token_counter import count_message_tokens
from agent.message import ASSISTANT, SYSTEM, TOOL, USER, Message

MISSING_TOOL_RESULT = "[系统] 该工具调用未执行或结果缺失。"


@dataclass
class WindowSelection:
    start: int
    messages: list[Message]
    tokens: int


def turn_starts(messages: list[Message]) -> list[int]:
    """找出每个对话轮次的起点下标（以 user 消息为界，兜底包含下标 0）。"""
    starts = [i for i, m in enumerate(messages) if m.role == USER]
    if messages and (not starts or starts[0] != 0):
        starts.insert(
            0,
            0,
        )
    return starts


def sanitize(messages: list[Message]) -> list[Message]:
    """清洗非法消息序列：丢弃 system 与孤立 tool，为未闭合 tool_calls 补占位结果。"""
    result: list[Message] = []
    open_ids: list[str] = []

    def close_open() -> None:
        for call_id in open_ids:
            result.append(
                Message(
                    role=TOOL,
                    tool_call_id=call_id,
                    content=MISSING_TOOL_RESULT,
                )
            )
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
    """按 Token 预算与 USER 轮次边界逆序挑选最近上下文，最新一轮始终保留。"""

    def __init__(
        self,
        max_tokens: int = 6000,
    ) -> None:
        self.max_tokens = max_tokens

    def select(
        self,
        messages: list[Message],
        reserved_tokens: int = 0,
    ) -> WindowSelection:
        if not messages:
            return WindowSelection(
                start=0,
                messages=[],
                tokens=0,
            )

        budget = max(
            0,
            self.max_tokens - reserved_tokens,
        )
        starts = turn_starts(messages)
        bounds = list(
            zip(
                starts,
                starts[1:] + [len(messages)],
            )
        )

        used = 0
        start = len(messages)
        for begin, end in reversed(bounds):
            turn_tokens = sum(count_message_tokens(m) for m in messages[begin:end])
            if used + turn_tokens > budget and start < len(messages):
                break
            used += turn_tokens
            start = begin

        return WindowSelection(
            start=start,
            messages=sanitize(messages[start:]),
            tokens=used,
        )