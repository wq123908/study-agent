"""L2 滚动摘要：把滑出上下文窗口的历史压缩为简短摘要，挂载到 system prompt 之后。"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from agent.message import ASSISTANT, SYSTEM, TOOL, USER, Message

if TYPE_CHECKING:  # pragma: no cover
    from agent.llm.provider import LLMClient

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """你是对话记忆压缩器。请把【已有摘要】与【新增对话】合并成一份新的摘要。
要求：
1. 不超过 {max_chars} 个汉字，使用简洁的要点式中文；
2. 保留：用户身份与偏好、关键事实与数字、已做出的决定、未完成的事项；
3. 删除寒暄和重复信息，不要编造对话中没有的内容；
4. 只输出摘要正文，不要任何前后缀。"""


def render_transcript(messages: list[Message], tool_preview: int = 200) -> str:
    lines: list[str] = []
    for m in messages:
        if m.role == USER:
            lines.append(f"用户: {m.content or ''}")
        elif m.role == ASSISTANT:
            if m.tool_calls:
                calls = "; ".join(f"{tc.name}({tc.arguments})" for tc in m.tool_calls)
                lines.append(f"助手调用工具: {calls}")
            if m.content:
                lines.append(f"助手: {m.content}")
        elif m.role == TOOL:
            lines.append(f"工具结果[{m.name or m.tool_call_id}]: {(m.content or '')[:tool_preview]}")
    return "\n".join(lines)


class Summarizer:
    def __init__(self, llm: "LLMClient", max_chars: int = 300) -> None:
        self.llm = llm
        self.max_chars = max_chars

    async def summarize(self, previous: str, messages: list[Message]) -> str:
        transcript = render_transcript(messages)
        prompt = [
            {"role": SYSTEM, "content": SUMMARY_PROMPT.format(max_chars=self.max_chars)},
            {"role": USER, "content": f"【已有摘要】\n{previous or '（无）'}\n\n【新增对话】\n{transcript}"},
        ]
        text = (await self.llm.complete(prompt, temperature=0.1)).strip()
        # 兜底：模型不听话时硬截断，防止摘要本身失控膨胀
        return text[: self.max_chars * 2]
