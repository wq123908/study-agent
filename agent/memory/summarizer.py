"""L2 滚动摘要：把滑出上下文窗口的历史压缩为简短摘要，挂载到 system prompt 之后。"""
from __future__ import annotations

from typing import TYPE_CHECKING

from agent.message import ASSISTANT, SYSTEM, TOOL, USER, Message

if TYPE_CHECKING:
    from agent.llm.provider import LLMClient

SUMMARY_PROMPT = """你是对话记忆压缩器。请把【已有摘要】与【新增对话】合并成一份新的摘要。
要求：
1. 不超过 {max_chars} 个汉字，使用简洁的要点式中文；
2. 保留：用户身份与偏好、关键事实与数字、已做出的决定、未完成的事项；
3. 删除寒暄和重复信息，不要编造对话中没有的内容；
4. 只输出摘要正文，不要任何前后缀。"""

def render_transcript(
    messages: list[Message],
    tool_preview: int = 200,
) -> str:
    """把滑出窗口的多角色消息压成紧凑纯文本剧本，供摘要模型阅读。"""
    lines: list[str] = []
    for m in messages:
        if m.role == USER:
            lines.append(f"用户: {m.content or ''}")
        elif m.role == ASSISTANT:
            if m.tool_calls:
                calls = "; ".join(
                    f"{tc.name}({tc.arguments})" for tc in m.tool_calls
                )
                lines.append(f"助手调用工具: {calls}")
            if m.content:
                lines.append(f"助手: {m.content}")
        elif m.role == TOOL:
            # 工具名缺失时回退用 tool_call_id，同时截断过长正文省 Token
            label = m.name or m.tool_call_id
            preview = (m.content or "")[:tool_preview]
            lines.append(f"工具结果[{label}]: {preview}")
    return "\n".join(lines)

class Summarizer:
    """滚雪球式 L2 摘要器：把【已有摘要】与【新增滑出对话】合并为精炼新摘要。"""

    def __init__(
        self,
        llm: "LLMClient",
        max_chars: int = 300,
    ) -> None:
        self.llm = llm
        self.max_chars = max_chars

    async def summarize(
        self,
        previous: str,
        messages: list[Message],
    ) -> str:
        transcript = render_transcript(messages)
        prompt = [
            {
                "role": SYSTEM,
                "content": SUMMARY_PROMPT.format(max_chars=self.max_chars),
            },
            {
                "role": USER,
                "content": (
                    f"【已有摘要】\n{previous or '（无）'}\n\n"
                    f"【新增对话】\n{transcript}"
                ),
            },
        ]
        # 用低温 0.1 抑制发散与脑补，确保忠实压缩已有事实
        text = (
            await self.llm.complete(
                prompt,
                temperature=0.1,
            )
        ).strip()
        # 兜底硬截断：万一模型不听话写出超长小作文，最多放行 2 倍字数防失控膨胀
        return text[: self.max_chars * 2]